"""Official NSE event acquisition and parsing for HTR-009A2."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from alpha.historical_truth.event_sourced_universe_models import (
    EventAdmissionState,
    EventConfidenceState,
    EventLineageRecord,
    EventRejectionRecord,
    EventSourceInventoryRecord,
    EventSourceSpec,
    EventSourceStatus,
    MembershipEffect,
    SecurityEventRecord,
    SecurityEventType,
    TradabilityEffect,
    identity_key,
    stable_event_id,
)

OFFICIAL_NSE_HOSTS = frozenset(
    {
        "nseindia.com",
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
    }
)
EVENT_SOURCE_HEADERS = {
    "Accept": "text/csv,application/gzip,application/pdf,application/octet-stream,*/*",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}


class HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str
    history: Sequence[Any]

    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class ParsedEventSource:
    inventory: EventSourceInventoryRecord
    events: tuple[SecurityEventRecord, ...]
    lineage: tuple[EventLineageRecord, ...]
    rejected: tuple[EventRejectionRecord, ...]


def default_event_source_specs(cutoff: date) -> tuple[EventSourceSpec, ...]:
    """Return the governed official source inventory for the requested cutoff."""

    checkpoint = min(cutoff, date(2025, 12, 31))
    stamp = checkpoint.strftime("%d%m%Y")
    return (
        EventSourceSpec(
            "nse_current_equity_listing_events",
            "LISTING_AND_ADMISSION",
            "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
            "nse_equity_listing_csv_v1",
            SecurityEventType.LISTED,
            current_only=True,
        ),
        EventSourceSpec(
            "nse_symbol_change_events",
            "IDENTITY_CHANGES",
            "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
            "nse_symbol_change_csv_v1",
            SecurityEventType.SYMBOL_CHANGED,
        ),
        EventSourceSpec(
            "nse_name_change_events",
            "IDENTITY_CHANGES",
            "https://nsearchives.nseindia.com/content/equities/namechange.csv",
            "nse_name_change_csv_v1",
            SecurityEventType.NAME_CHANGED,
        ),
        EventSourceSpec(
            f"nse_cm_checkpoint_{stamp}",
            "CHECKPOINT_MASTER",
            (
                "https://nsearchives.nseindia.com/content/cm/"
                f"NSE_CM_security_{stamp}.csv.gz"
            ),
            "nse_mii_checkpoint_csv_v1",
            SecurityEventType.CHECKPOINT_PRESENT,
            effective_date=checkpoint,
        ),
        EventSourceSpec(
            "nse_suspension_events",
            "TEMPORARY_STATUS",
            "https://nsearchives.nseindia.com/content/equities/suspended.csv",
            "nse_suspension_csv_v1",
            SecurityEventType.SUSPENDED,
        ),
        EventSourceSpec(
            "nse_delisting_events",
            "TERMINATION",
            "https://nsearchives.nseindia.com/content/equities/delisted.csv",
            "nse_delisting_csv_v1",
            SecurityEventType.DELISTED,
        ),
    )


class OfficialSecurityEventStore:
    """Retain official bytes immutably and derive deterministic event records."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root / "raw" / "nse" / "security_events" / "historical"
        self._now = now or (lambda: datetime.now(UTC))

    def acquire(
        self,
        specs: Sequence[EventSourceSpec],
        *,
        session: HttpSession | None = None,
        timeout_seconds: float = 30.0,
    ) -> tuple[ParsedEventSource, ...]:
        client = (
            session if session is not None else cast(HttpSession, requests.Session())
        )
        return tuple(self._acquire_one(spec, client, timeout_seconds) for spec in specs)

    def verify_or_missing(
        self,
        specs: Sequence[EventSourceSpec],
    ) -> tuple[ParsedEventSource, ...]:
        return tuple(self._reuse_one(spec) for spec in specs)

    def _acquire_one(
        self,
        spec: EventSourceSpec,
        session: HttpSession,
        timeout_seconds: float,
    ) -> ParsedEventSource:
        host = (urlparse(spec.url).hostname or "").lower()
        if not _official_host(host):
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                "UNOFFICIAL_HOST",
                f"host {host or 'missing'} is not an approved NSE host",
            )
        if not self._source_date_matches(spec):
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                "WRONG_EFFECTIVE_DATE",
                "source URL date does not match the governed effective date",
            )
        try:
            response = session.get(
                spec.url,
                headers=EVENT_SOURCE_HEADERS,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return self._terminal(
                spec,
                EventSourceStatus.FAILED,
                "NETWORK_OR_HTTP_ERROR",
                str(exc),
                http_status=status,
            )
        except Exception as exc:
            return self._terminal(
                spec,
                EventSourceStatus.FAILED,
                "NETWORK_OR_HTTP_ERROR",
                str(exc),
            )
        final_host = (urlparse(response.url).hostname or "").lower()
        content_type = response.headers.get("Content-Type")
        redirects = tuple(str(item.url) for item in response.history) + (
            str(response.url),
        )
        if not _official_host(final_host):
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                "UNOFFICIAL_REDIRECT",
                f"final host {final_host or 'missing'} is not approved",
                http_status=response.status_code,
                content_type=content_type,
                redirects=redirects,
            )
        raw = response.content
        validation = _validate_document(raw, content_type)
        if validation is not None:
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                validation,
                "source bytes failed document validation",
                http_status=response.status_code,
                content_type=content_type,
                redirects=redirects,
                byte_size=len(raw),
            )
        digest = hashlib.sha256(raw).hexdigest()
        suffix = ".csv.gz" if raw.startswith(b"\x1f\x8b") else ".csv"
        year = spec.effective_date.year if spec.effective_date else "reference"
        directory = self.root / str(year)
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / f"{spec.source_id}_{digest}{suffix}"
        if source_path.exists() and source_path.read_bytes() != raw:
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                "CHECKSUM_PATH_CONFLICT",
                str(source_path),
                byte_size=len(raw),
            )
        if not source_path.exists():
            source_path.write_bytes(raw)
        parsed = _parse_source(spec, raw, digest)
        retrieved = self._now().astimezone(UTC).isoformat()
        manifest_path = source_path.with_suffix(source_path.suffix + ".manifest.json")
        existing = _read_json(manifest_path)
        if existing is not None:
            retrieved = str(existing.get("retrieval_timestamp") or retrieved)
        inventory = EventSourceInventoryRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            True,
            _document_id(spec.url),
            retrieved,
            response.status_code,
            content_type,
            len(raw),
            redirects,
            digest,
            str(source_path),
            spec.parser,
            parsed[0],
            len(parsed[1]),
            sum(
                event.admission_state is EventAdmissionState.ADMITTED
                for event in parsed[1]
            ),
            len(parsed[3])
            + sum(
                event.admission_state is not EventAdmissionState.ADMITTED
                for event in parsed[1]
            ),
            EventSourceStatus.ACQUIRED,
            None,
            None,
        )
        if existing is None:
            manifest_path.write_text(
                json.dumps(_jsonable(asdict(inventory)), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        return ParsedEventSource(inventory, parsed[1], parsed[2], parsed[3])

    def _reuse_one(self, spec: EventSourceSpec) -> ParsedEventSource:
        manifest = self._latest_manifest(spec.source_id)
        if manifest is None:
            return self._terminal(
                spec,
                EventSourceStatus.FAILED,
                "IMMUTABLE_SOURCE_NOT_FOUND",
                "verification-only mode cannot acquire missing official evidence",
            )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            source_path = Path(str(payload["source_path"]))
            raw = source_path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            expected = str(payload["sha256"])
            if actual != expected:
                return self._terminal(
                    spec,
                    EventSourceStatus.REJECTED,
                    "CHECKSUM_MISMATCH",
                    f"expected {expected}; observed {actual}",
                )
            parsed = _parse_source(spec, raw, actual)
            inventory = EventSourceInventoryRecord(
                spec.source_id,
                spec.source_family,
                spec.url,
                True,
                _document_id(spec.url),
                str(payload.get("retrieval_timestamp") or "") or None,
                _optional_int(payload.get("http_status")),
                _optional_str(payload.get("content_type")),
                len(raw),
                tuple(str(item) for item in payload.get("redirects", ())),
                actual,
                str(source_path),
                spec.parser,
                parsed[0],
                len(parsed[1]),
                sum(
                    event.admission_state is EventAdmissionState.ADMITTED
                    for event in parsed[1]
                ),
                len(parsed[3])
                + sum(
                    event.admission_state is not EventAdmissionState.ADMITTED
                    for event in parsed[1]
                ),
                EventSourceStatus.REUSED,
                None,
                None,
            )
            return ParsedEventSource(inventory, parsed[1], parsed[2], parsed[3])
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._terminal(
                spec,
                EventSourceStatus.REJECTED,
                "INVALID_MANIFEST",
                str(exc),
            )

    def _latest_manifest(self, source_id: str) -> Path | None:
        paths = tuple(sorted(self.root.glob(f"**/{source_id}_*.manifest.json")))
        if not paths:
            return None
        return max(
            paths,
            key=lambda path: (
                str((_read_json(path) or {}).get("retrieval_timestamp", "")),
                str(path),
            ),
        )

    @staticmethod
    def _source_date_matches(spec: EventSourceSpec) -> bool:
        match = re.search(r"security_(\d{8})", spec.url, flags=re.IGNORECASE)
        if match is None or spec.effective_date is None:
            return True
        return match.group(1) == spec.effective_date.strftime("%d%m%Y")

    def _terminal(
        self,
        spec: EventSourceSpec,
        status: EventSourceStatus,
        code: str,
        detail: str,
        *,
        http_status: int | None = None,
        content_type: str | None = None,
        redirects: tuple[str, ...] = (),
        byte_size: int = 0,
    ) -> ParsedEventSource:
        inventory = EventSourceInventoryRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            _official_host((urlparse(spec.url).hostname or "").lower()),
            _document_id(spec.url),
            self._now().astimezone(UTC).isoformat(),
            http_status,
            content_type,
            byte_size,
            redirects,
            None,
            None,
            spec.parser,
            0,
            0,
            0,
            1,
            status,
            code,
            detail,
        )
        rejection = EventRejectionRecord(spec.source_id, spec.url, code, detail)
        return ParsedEventSource(inventory, (), (), (rejection,))


def _parse_source(
    spec: EventSourceSpec,
    raw: bytes,
    digest: str,
) -> tuple[
    int,
    tuple[SecurityEventRecord, ...],
    tuple[EventLineageRecord, ...],
    tuple[EventRejectionRecord, ...],
]:
    decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    text = decoded.decode("utf-8-sig", errors="replace")
    if spec.parser == "nse_symbol_change_csv_v1":
        reader = csv.DictReader(
            io.StringIO(text),
            fieldnames=("company_name", "old_symbol", "new_symbol", "effective_date"),
        )
    else:
        reader = csv.DictReader(io.StringIO(text))
    events: list[SecurityEventRecord] = []
    lineage: list[EventLineageRecord] = []
    rejected: list[EventRejectionRecord] = []
    seen: set[str] = set()
    inspected = 0
    for row_number, raw_row in enumerate(reader, 2):
        inspected += 1
        row = _normalized_row(raw_row)
        if not any(row.values()):
            continue
        segment = _field(row, "segment", "sgmt", "market_segment")
        if segment and segment.upper() not in {"CM", "CAPITAL MARKET"}:
            rejected.append(
                EventRejectionRecord(
                    spec.source_id,
                    spec.url,
                    "WRONG_SEGMENT",
                    f"expected CM; observed {segment}",
                    row_number,
                )
            )
            continue
        parsed_events = _events_from_row(spec, row)
        if isinstance(parsed_events, str):
            rejected.append(
                EventRejectionRecord(
                    spec.source_id,
                    spec.url,
                    parsed_events,
                    "source row cannot support a governed event",
                    row_number,
                    _field(row, "symbol", "tckrsymb", "old_symbol"),
                )
            )
            continue
        for parsed in parsed_events:
            if parsed.event_id in seen:
                rejected.append(
                    EventRejectionRecord(
                        spec.source_id,
                        spec.url,
                        "DUPLICATE_EVENT",
                        "duplicate deterministic event",
                        row_number,
                        parsed.event_id,
                    )
                )
                continue
            seen.add(parsed.event_id)
            events.append(parsed)
            lineage.append(
                EventLineageRecord(
                    parsed.event_id,
                    spec.source_id,
                    digest,
                    spec.url,
                    spec.parser,
                    row_number,
                )
            )
    ordered_events = tuple(
        sorted(events, key=lambda item: (item.effective_date, item.event_id))
    )
    ordered_lineage = tuple(sorted(lineage, key=lambda item: item.event_id))
    return inspected, ordered_events, ordered_lineage, tuple(rejected)


def _events_from_row(
    spec: EventSourceSpec,
    row: Mapping[str, str],
) -> tuple[SecurityEventRecord, ...] | str:
    primary = _event_from_row(spec, row)
    if isinstance(primary, str):
        return primary
    if spec.parser != "nse_mii_checkpoint_csv_v1":
        return (primary,)
    events = [primary]
    listing_date = _parse_date(_field(row, "listgdt", "listing_date"))
    if listing_date is not None:
        events.append(
            _derived_boundary_event(
                primary,
                SecurityEventType.LISTED,
                listing_date,
            )
        )
    removal_date = _parse_date(_field(row, "rmvldt", "removal_date"))
    if removal_date is not None:
        events.append(
            _derived_boundary_event(
                primary,
                SecurityEventType.DELISTED,
                removal_date,
            )
        )
    return tuple(events)


def _event_from_row(
    spec: EventSourceSpec,
    row: Mapping[str, str],
) -> SecurityEventRecord | str:
    old_symbol = _field(row, "old_symbol", "oldsymbol", "previous_symbol") or None
    new_symbol = (
        _field(
            row,
            "new_symbol",
            "newsymbol",
            "symbol",
            "nch_symbol",
            "tckrsymb",
            "security_symbol",
        )
        or None
    )
    old_series = _field(row, "old_series", "oldseries") or None
    new_series = (
        _field(
            row,
            "new_series",
            "newseries",
            "series",
            "sctysrs",
            "security_series",
        )
        or None
    )
    old_isin = _field(row, "old_isin", "oldisin") or None
    new_isin = (
        _field(
            row,
            "new_isin",
            "newisin",
            "isin",
            "isin_number",
            "isin_no",
        )
        or None
    )
    event_date = _event_date(spec, row)
    if event_date is None:
        return "MISSING_OR_INVALID_EFFECTIVE_DATE"
    if new_isin and identity_key(new_isin) is None:
        return "MALFORMED_ISIN"
    if old_isin and identity_key(old_isin) is None:
        return "MALFORMED_ISIN"
    event_type = _event_type(spec, row)
    if not (new_symbol or old_symbol or new_isin or old_isin):
        return "MISSING_IDENTITY_FIELDS"
    membership_effect, tradability_effect = _effects(event_type)
    security_name = (
        _field(
            row,
            "security_name",
            "name_of_company",
            "company_name",
            "company",
            "name",
            "nch_new_name",
            "fininstrmnm",
        )
        or None
    )
    predecessor = identity_key(old_isin)
    successor = identity_key(new_isin)
    event_id = stable_event_id(
        spec.source_id,
        event_type,
        event_date,
        old_symbol,
        new_symbol,
        old_series,
        new_series,
        old_isin,
        new_isin,
        security_name,
    )
    admission_state = EventAdmissionState.ADMITTED
    if event_type is SecurityEventType.CHECKPOINT_PRESENT:
        eligible = _field(row, "elgbltynrmlmkt", "normal_market_eligibility")
        deleted = _field(row, "delflg", "delete_flag").upper()
        if (eligible and eligible != "1") or deleted == "Y":
            admission_state = EventAdmissionState.PROVISIONAL
    return SecurityEventRecord(
        event_id,
        "NSE",
        event_type,
        event_date,
        _parse_date(_field(row, "announcement_date", "circular_date")),
        old_symbol.upper() if old_symbol else None,
        new_symbol.upper() if new_symbol else None,
        old_series.upper() if old_series else None,
        new_series.upper() if new_series else None,
        old_isin.upper() if old_isin else None,
        new_isin.upper() if new_isin else None,
        security_name,
        predecessor,
        successor,
        membership_effect,
        tradability_effect,
        spec.source_id,
        spec.url,
        admission_state,
        EventConfidenceState.HIGH,
    )


def _derived_boundary_event(
    checkpoint: SecurityEventRecord,
    event_type: SecurityEventType,
    effective_date: date,
) -> SecurityEventRecord:
    membership_effect, tradability_effect = _effects(event_type)
    event_id = stable_event_id(
        checkpoint.official_source_id,
        event_type,
        effective_date,
        checkpoint.new_symbol,
        checkpoint.new_series,
        checkpoint.new_isin,
        checkpoint.security_name,
    )
    return SecurityEventRecord(
        event_id,
        checkpoint.exchange,
        event_type,
        effective_date,
        checkpoint.announcement_date,
        checkpoint.old_symbol,
        checkpoint.new_symbol,
        checkpoint.old_series,
        checkpoint.new_series,
        checkpoint.old_isin,
        checkpoint.new_isin,
        checkpoint.security_name,
        checkpoint.predecessor_identity,
        checkpoint.successor_identity,
        membership_effect,
        tradability_effect,
        checkpoint.official_source_id,
        checkpoint.document_location,
        EventAdmissionState.ADMITTED,
        checkpoint.confidence_state,
    )


def _event_type(spec: EventSourceSpec, row: Mapping[str, str]) -> SecurityEventType:
    status = _field(row, "status", "action", "event_type", "remarks").upper()
    if spec.event_type is SecurityEventType.SUSPENDED and any(
        item in status for item in ("REVOK", "RESTOR", "RESUM")
    ):
        return SecurityEventType.SUSPENSION_REVOKED
    if spec.event_type is SecurityEventType.DELISTED and "WITHDRAW" in status:
        return SecurityEventType.ADMISSION_WITHDRAWN
    return spec.event_type


def _event_date(spec: EventSourceSpec, row: Mapping[str, str]) -> date | None:
    if spec.event_type is SecurityEventType.LISTED:
        value = _field(
            row,
            "date_of_listing",
            "listing_date",
            "listgdt",
            "effective_date",
            "date",
        )
    elif spec.event_type is SecurityEventType.CHECKPOINT_PRESENT:
        return spec.effective_date
    else:
        value = _field(
            row,
            "effective_date",
            "date",
            "suspension_date",
            "delisting_date",
            "delisted_date",
            "from_date",
            "nch_dt",
        )
    return _parse_date(value) or spec.effective_date


def _effects(
    event_type: SecurityEventType,
) -> tuple[MembershipEffect, TradabilityEffect]:
    if event_type in {
        SecurityEventType.LISTED,
        SecurityEventType.ADMITTED_TO_TRADING,
        SecurityEventType.RELISTED,
        SecurityEventType.SUCCESSOR_CREATED,
    }:
        return MembershipEffect.OPEN, TradabilityEffect.OPEN
    if event_type is SecurityEventType.SUSPENDED:
        return MembershipEffect.UNCHANGED, TradabilityEffect.CLOSE
    if event_type is SecurityEventType.SUSPENSION_REVOKED:
        return MembershipEffect.UNCHANGED, TradabilityEffect.OPEN
    if event_type in {
        SecurityEventType.DELISTED,
        SecurityEventType.ADMISSION_WITHDRAWN,
        SecurityEventType.IDENTITY_TERMINATED,
        SecurityEventType.MERGED,
        SecurityEventType.AMALGAMATED,
    }:
        return MembershipEffect.CLOSE, TradabilityEffect.CLOSE
    return MembershipEffect.UNCHANGED, TradabilityEffect.UNCHANGED


def _parse_date(value: str) -> date | None:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() in {"null", "none", "na", "n.a."}:
        return None
    if cleaned.isdigit():
        timestamp = int(cleaned)
        if timestamp > 100_000_000:
            try:
                return datetime.fromtimestamp(timestamp, tz=UTC).date()
            except (OverflowError, OSError, ValueError):
                return None
    for pattern in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d %b %Y",
        "%d-%b-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def _normalized_row(raw_row: Mapping[str | None, object]) -> dict[str, str]:
    return {
        str(key).strip().lower().replace(" ", "_"): str(value or "").strip()
        for key, value in raw_row.items()
        if key is not None
    }


def _field(row: Mapping[str, str], *names: str) -> str:
    return next((row[name] for name in names if row.get(name)), "")


def _validate_document(raw: bytes, content_type: str | None) -> str | None:
    if not raw:
        return "EMPTY_RESPONSE"
    prefix = raw[:512].lower().lstrip()
    if prefix.startswith((b"<!doctype html", b"<html")):
        return "HTML_MASQUERADING_AS_DATA"
    if content_type and "html" in content_type.lower():
        return "HTML_MASQUERADING_AS_DATA"
    try:
        decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    except (gzip.BadGzipFile, EOFError):
        return "INVALID_GZIP"
    if b"," not in decoded[:8192]:
        return "UNEXPECTED_DOCUMENT_TYPE"
    return None


def _official_host(host: str) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in OFFICIAL_NSE_HOSTS)


def _document_id(url: str) -> str | None:
    name = Path(urlparse(url).path).name
    return name or None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _optional_int(value: object) -> int | None:
    return (
        int(value) if isinstance(value, (int, str)) and str(value).isdigit() else None
    )


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


__all__ = [
    "EVENT_SOURCE_HEADERS",
    "OFFICIAL_NSE_HOSTS",
    "OfficialSecurityEventStore",
    "ParsedEventSource",
    "default_event_source_specs",
]
