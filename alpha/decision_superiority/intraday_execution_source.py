"""Candidate-bounded Upstox V3 source acquisition and five-minute validation."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from alpha.decision_superiority.intraday_execution_models import (
    DSI013_SOURCE_ID,
    IntradayBar,
    IntradayBarDisposition,
    IntradayExecutionError,
    IntradayExecutionPolicy,
    IntradayReadiness,
    IntradaySourceAudit,
    IntradaySourceRequest,
)

UPSTOX_V3_HISTORICAL_BASE_URL = "https://api.upstox.com/v3/historical-candle"
IST_OFFSET = timedelta(hours=5, minutes=30)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal immutable HTTP response used by the acquisition adapter."""

    status_code: int
    body: bytes
    content_type: str | None = None


class BinaryHttpTransport(Protocol):
    """Injectable HTTP transport for deterministic source acquisition tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse: ...


class UrllibBinaryHttpTransport:
    """Standard-library HTTPS transport with no credential persistence."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                body: bytes = response.read()
                status = int(response.status)
                content_type = response.headers.get("Content-Type")
        except HTTPError as exc:
            body = exc.read()
            raise IntradayExecutionError(
                f"DSI013_UPSTOX_HTTP_ERROR:{exc.code}:{body[:200]!r}"
            ) from exc
        except URLError as exc:
            raise IntradayExecutionError("DSI013_UPSTOX_NETWORK_ERROR") from exc
        return HttpResponse(status_code=status, body=body, content_type=content_type)


def upstox_v3_request_url(
    request: IntradaySourceRequest,
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> str:
    """Build the frozen Upstox V3 candidate-window request URL."""

    active_policy = policy or IntradayExecutionPolicy()
    encoded_key = quote(request.instrument_key, safe="")
    return (
        f"{UPSTOX_V3_HISTORICAL_BASE_URL}/{encoded_key}/minutes/"
        f"{active_policy.interval_minutes}/{request.to_date.isoformat()}/"
        f"{request.from_date.isoformat()}"
    )


def source_request_id(
    request: IntradaySourceRequest,
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> str:
    """Return a stable content identity for one source request."""

    payload = source_request_payload(request, policy=policy)
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_request_payload(
    request: IntradaySourceRequest,
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> dict[str, Any]:
    """Return the credential-free request descriptor stored in source manifests."""

    active_policy = policy or IntradayExecutionPolicy()
    return {
        "source_id": DSI013_SOURCE_ID,
        "governed_identity": request.governed_identity,
        "instrument_key": request.instrument_key,
        "unit": "minutes",
        "interval": active_policy.interval_minutes,
        "from_date": request.from_date.isoformat(),
        "to_date": request.to_date.isoformat(),
        "timezone": active_policy.timezone_name,
    }


def cache_paths(
    cache_root: Path,
    request: IntradaySourceRequest,
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> tuple[Path, Path]:
    """Return immutable raw-response and manifest paths for one request."""

    request_id = source_request_id(request, policy=policy)
    directory = cache_root / DSI013_SOURCE_ID.lower()
    return directory / f"{request_id}.json", directory / f"{request_id}.manifest.json"


def fetch_upstox_v3_bars(
    request: IntradaySourceRequest,
    *,
    access_token: str,
    cache_root: Path,
    policy: IntradayExecutionPolicy | None = None,
    transport: BinaryHttpTransport | None = None,
    retrieved_at: datetime | None = None,
) -> tuple[IntradayBar, ...]:
    """Fetch or replay one immutable candidate-bounded Upstox response."""

    active_policy = policy or IntradayExecutionPolicy()
    if not access_token.strip():
        raise IntradayExecutionError("DSI013_UPSTOX_ACCESS_TOKEN_MISSING")
    raw_path, manifest_path = cache_paths(cache_root, request, policy=active_policy)
    if raw_path.is_file() or manifest_path.is_file():
        payload = _load_verified_cache(raw_path, manifest_path, request, active_policy)
        return parse_upstox_v3_payload(payload, request=request, policy=active_policy)

    active_transport = transport or UrllibBinaryHttpTransport()
    response = active_transport.get(
        upstox_v3_request_url(request, policy=active_policy),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        timeout_seconds=active_policy.request_timeout_seconds,
    )
    if response.status_code != 200:
        raise IntradayExecutionError(
            f"DSI013_UPSTOX_HTTP_STATUS_INVALID:{response.status_code}"
        )
    payload = _decode_payload(response.body)
    timestamp = retrieved_at or datetime.now(UTC)
    _write_source_cache(
        raw_path=raw_path,
        manifest_path=manifest_path,
        raw=response.body,
        request=request,
        policy=active_policy,
        retrieved_at=timestamp,
        content_type=response.content_type,
    )
    return parse_upstox_v3_payload(payload, request=request, policy=active_policy)


def parse_upstox_v3_payload(
    payload: Mapping[str, Any],
    *,
    request: IntradaySourceRequest,
    policy: IntradayExecutionPolicy | None = None,
) -> tuple[IntradayBar, ...]:
    """Parse a V3 response without repairing or forward-filling missing evidence."""

    del policy
    if payload.get("status") != "success":
        raise IntradayExecutionError("DSI013_UPSTOX_RESPONSE_NOT_SUCCESS")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise IntradayExecutionError("DSI013_UPSTOX_DATA_SCHEMA_INVALID")
    candles = data.get("candles")
    if not isinstance(candles, list):
        raise IntradayExecutionError("DSI013_UPSTOX_CANDLES_SCHEMA_INVALID")

    bars: list[IntradayBar] = []
    for index, raw_row in enumerate(candles):
        if not isinstance(raw_row, list) or len(raw_row) < 6:
            raise IntradayExecutionError(
                f"DSI013_UPSTOX_CANDLE_ROW_INVALID:{index}"
            )
        try:
            timestamp = datetime.fromisoformat(str(raw_row[0]))
            open_price = float(raw_row[1])
            high = float(raw_row[2])
            low = float(raw_row[3])
            close = float(raw_row[4])
            volume = int(raw_row[5])
            open_interest = int(raw_row[6]) if len(raw_row) > 6 else 0
        except (TypeError, ValueError) as exc:
            raise IntradayExecutionError(
                f"DSI013_UPSTOX_CANDLE_VALUE_INVALID:{index}"
            ) from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() != IST_OFFSET:
            raise IntradayExecutionError(
                f"DSI013_UPSTOX_TIMESTAMP_TIMEZONE_INVALID:{index}"
            )
        if not request.from_date <= timestamp.date() <= request.to_date:
            raise IntradayExecutionError(
                f"DSI013_UPSTOX_TIMESTAMP_OUTSIDE_REQUEST:{index}"
            )
        bars.append(
            IntradayBar(
                governed_identity=request.governed_identity,
                instrument_key=request.instrument_key,
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                open_interest=open_interest,
            )
        )
    return tuple(sorted(bars, key=lambda bar: bar.timestamp))


def audit_intraday_bars(
    bars: Sequence[IntradayBar],
    *,
    policy: IntradayExecutionPolicy | None = None,
    regular_session_dates: frozenset[date] | None = None,
) -> IntradaySourceAudit:
    """Validate five-minute bars and regular-session completeness fail-closed."""

    active_policy = policy or IntradayExecutionPolicy()
    validation_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    seen: set[tuple[str, datetime]] = set()
    grouped: defaultdict[date, list[IntradayBar]] = defaultdict(list)

    for bar in sorted(bars, key=lambda item: (item.timestamp, item.instrument_key)):
        disposition = _bar_disposition(bar, active_policy, seen)
        validation_rows.append(
            {
                "governed_identity": bar.governed_identity,
                "instrument_key": bar.instrument_key,
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "open_interest": bar.open_interest,
                "disposition": disposition.value,
            }
        )
        if disposition is not IntradayBarDisposition.ADMITTED:
            blockers.append(f"{disposition.value}:{bar.timestamp.isoformat()}")
        else:
            grouped[bar.timestamp.date()].append(bar)
        seen.add((bar.instrument_key, bar.timestamp))

    session_rows: list[dict[str, Any]] = []
    for session_date, session_bars in sorted(grouped.items()):
        ordered = sorted(session_bars, key=lambda item: item.timestamp)
        expected_regular = (
            regular_session_dates is None or session_date in regular_session_dates
        )
        first_time = ordered[0].timestamp.timetz().replace(tzinfo=None)
        last_time = ordered[-1].timestamp.timetz().replace(tzinfo=None)
        expected_last_time = _last_bar_start(
            active_policy.session_end,
            active_policy.interval_minutes,
        )
        count_ok = (
            not expected_regular
            or len(ordered) == active_policy.expected_regular_bar_count
        )
        boundary_ok = (
            not expected_regular
            or (
                first_time == active_policy.session_start
                and last_time == expected_last_time
            )
        )
        if not count_ok:
            blockers.append(
                f"SESSION_BAR_COUNT_MISMATCH:{session_date.isoformat()}:{len(ordered)}"
            )
        if not boundary_ok:
            blockers.append(
                f"SESSION_BOUNDARY_MISMATCH:{session_date.isoformat()}:{first_time}:{last_time}"
            )
        session_rows.append(
            {
                "session_date": session_date.isoformat(),
                "bar_count": len(ordered),
                "expected_bar_count": (
                    active_policy.expected_regular_bar_count
                    if expected_regular
                    else "SPECIAL_SESSION"
                ),
                "first_bar": ordered[0].timestamp.isoformat(),
                "last_bar": ordered[-1].timestamp.isoformat(),
                "session_open": ordered[0].open,
                "session_high": max(bar.high for bar in ordered),
                "session_low": min(bar.low for bar in ordered),
                "session_close": ordered[-1].close,
                "session_volume": sum(bar.volume for bar in ordered),
                "count_passed": count_ok,
                "boundary_passed": boundary_ok,
            }
        )

    readiness = (
        IntradayReadiness.SOURCE_READY
        if not blockers
        else IntradayReadiness.SESSION_INTEGRITY_DEFECT
    )
    return IntradaySourceAudit(
        readiness=readiness,
        blockers=tuple(sorted(set(blockers))),
        bars=tuple(sorted(bars, key=lambda item: item.timestamp)),
        validation_rows=tuple(validation_rows),
        session_rows=tuple(session_rows),
    )


def _bar_disposition(
    bar: IntradayBar,
    policy: IntradayExecutionPolicy,
    seen: set[tuple[str, datetime]],
) -> IntradayBarDisposition:
    key = (bar.instrument_key, bar.timestamp)
    if key in seen:
        return IntradayBarDisposition.DUPLICATE_TIMESTAMP
    local_time = bar.timestamp.timetz().replace(tzinfo=None)
    if (
        bar.timestamp.second != 0
        or bar.timestamp.microsecond != 0
        or bar.timestamp.minute % policy.interval_minutes != 0
    ):
        return IntradayBarDisposition.TIMESTAMP_MISALIGNED
    if not policy.session_start <= local_time < policy.session_end:
        return IntradayBarDisposition.OFF_SESSION
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        return IntradayBarDisposition.NON_POSITIVE_PRICE
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        return IntradayBarDisposition.IMPOSSIBLE_OHLC
    if bar.low > bar.high:
        return IntradayBarDisposition.IMPOSSIBLE_OHLC
    if bar.volume < 0:
        return IntradayBarDisposition.NEGATIVE_VOLUME
    if bar.open_interest < 0:
        return IntradayBarDisposition.NEGATIVE_OPEN_INTEREST
    return IntradayBarDisposition.ADMITTED


def _last_bar_start(session_end: time, interval_minutes: int) -> time:
    end_minutes = session_end.hour * 60 + session_end.minute - interval_minutes
    return time(end_minutes // 60, end_minutes % 60)


def _write_source_cache(
    *,
    raw_path: Path,
    manifest_path: Path,
    raw: bytes,
    request: IntradaySourceRequest,
    policy: IntradayExecutionPolicy,
    retrieved_at: datetime,
    content_type: str | None,
) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    manifest = {
        "request": source_request_payload(request, policy=policy),
        "request_id": source_request_id(request, policy=policy),
        "request_url": upstox_v3_request_url(request, policy=policy),
        "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
        "content_type": content_type,
        "raw_sha256": digest,
        "credential_fields_persisted": False,
    }
    _atomic_write(raw_path, raw)
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )


def _load_verified_cache(
    raw_path: Path,
    manifest_path: Path,
    request: IntradaySourceRequest,
    policy: IntradayExecutionPolicy,
) -> Mapping[str, Any]:
    if not raw_path.is_file() or not manifest_path.is_file():
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_PARTIAL")
    try:
        raw = raw_path.read_bytes()
        manifest_value: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_UNREADABLE") from exc
    if not isinstance(manifest_value, Mapping):
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_MANIFEST_INVALID")
    manifest = cast(Mapping[str, Any], manifest_value)
    if manifest.get("request") != source_request_payload(request, policy=policy):
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_REQUEST_MISMATCH")
    if manifest.get("request_id") != source_request_id(request, policy=policy):
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_ID_MISMATCH")
    if manifest.get("raw_sha256") != hashlib.sha256(raw).hexdigest():
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_TAMPERED")
    if manifest.get("credential_fields_persisted") is not False:
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_CREDENTIAL_POLICY_INVALID")
    if b"Bearer " in raw or b"Authorization" in raw:
        raise IntradayExecutionError("DSI013_SOURCE_CACHE_SECRET_LEAK")
    return _decode_payload(raw)


def _decode_payload(raw: bytes) -> Mapping[str, Any]:
    try:
        value: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntradayExecutionError("DSI013_UPSTOX_RESPONSE_UNREADABLE") from exc
    if not isinstance(value, Mapping):
        raise IntradayExecutionError("DSI013_UPSTOX_RESPONSE_SCHEMA_INVALID")
    return cast(Mapping[str, Any], value)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


__all__ = [
    "BinaryHttpTransport",
    "HttpResponse",
    "UPSTOX_V3_HISTORICAL_BASE_URL",
    "UrllibBinaryHttpTransport",
    "audit_intraday_bars",
    "cache_paths",
    "fetch_upstox_v3_bars",
    "parse_upstox_v3_payload",
    "source_request_id",
    "source_request_payload",
    "upstox_v3_request_url",
]
