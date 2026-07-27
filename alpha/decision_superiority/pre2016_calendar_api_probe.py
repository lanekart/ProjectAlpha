"""Fail-closed probe for official NSE historical holiday API support."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import requests

from .pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    Pre2016ExternalValidationError,
)

_NSE_HOLIDAY_PAGE = "https://www.nseindia.com/resources/exchange-communication-holidays"
_NSE_HOLIDAY_API = "https://www.nseindia.com/api/holiday-master"


class _HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]

    def json(self) -> object: ...


class _HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse: ...


@dataclass(frozen=True, slots=True)
class Pre2016HolidayApiProbeAttempt:
    """One immutable request/response interpretation."""

    year: int
    variant_id: str
    request_url: str
    http_status: int | None
    content_type: str
    response_sha256: str | None
    response_bytes: int
    payload_state: str
    cm_row_count: int
    in_year_row_count: int
    out_of_year_row_count: int
    covered_years: tuple[int, ...]
    accepted_as_official_year_source: bool
    raw_path: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class Pre2016HolidayApiProbeResult:
    """All official API probes for the frozen external era."""

    attempts: tuple[Pre2016HolidayApiProbeAttempt, ...]
    requested_years: tuple[int, ...]
    accepted_years: tuple[int, ...]
    missing_years: tuple[int, ...]


def probe_pre2016_holiday_api(
    *,
    output: Path,
    years: tuple[int, ...] = tuple(range(2005, 2016)),
    timeout_seconds: float = 30.0,
    session: _HttpSession | None = None,
) -> Pre2016HolidayApiProbeResult:
    """Probe official NSE endpoints without accepting unsupported payloads."""

    requested_years = _validate_years(years)
    output.mkdir(parents=True, exist_ok=True)
    raw_root = output / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    client: _HttpSession = session or requests.Session()
    headers = {
        "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": _NSE_HOLIDAY_PAGE,
    }
    try:
        client.get(_NSE_HOLIDAY_PAGE, headers=headers, timeout=timeout_seconds)
    except requests.RequestException:
        pass

    attempts: list[Pre2016HolidayApiProbeAttempt] = []
    for year in requested_years:
        variants = (
            ("YEAR_ONLY", {"type": "trading", "year": str(year)}),
            (
                "YEAR_PRODUCT_CM",
                {"type": "trading", "year": str(year), "product": "CM"},
            ),
        )
        for variant_id, params in variants:
            attempts.append(
                _probe_attempt(
                    client=client,
                    year=year,
                    variant_id=variant_id,
                    params=params,
                    raw_root=raw_root,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                )
            )

    accepted_years = tuple(
        sorted(
            {
                attempt.year
                for attempt in attempts
                if attempt.accepted_as_official_year_source
            }
        )
    )
    missing_years = tuple(
        year for year in requested_years if year not in accepted_years
    )
    return Pre2016HolidayApiProbeResult(
        attempts=tuple(attempts),
        requested_years=requested_years,
        accepted_years=accepted_years,
        missing_years=missing_years,
    )


def export_pre2016_holiday_api_probe(
    result: Pre2016HolidayApiProbeResult,
    output: Path,
) -> tuple[Path, Path]:
    """Export probe attempts and fail-closed coverage summary."""

    output.mkdir(parents=True, exist_ok=True)
    attempts_path = output / "dsi010_pre2016_holiday_api_probe.csv"
    summary_path = output / "dsi010_pre2016_holiday_api_probe_summary.json"

    with attempts_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = tuple(asdict(result.attempts[0])) if result.attempts else (
            "year",
            "variant_id",
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for attempt in result.attempts:
            row = asdict(attempt)
            row["covered_years"] = ";".join(
                str(year) for year in attempt.covered_years
            )
            writer.writerow(row)

    summary = {
        "requested_years": list(result.requested_years),
        "accepted_years": list(result.accepted_years),
        "missing_years": list(result.missing_years),
        "attempt_count": len(result.attempts),
        "historical_year_api_support": not result.missing_years,
        "api_payload_used_as_calendar_evidence": bool(result.accepted_years),
        "unsupported_or_current_year_payloads_rejected": True,
        "classification_inferred_from_http_404": False,
        "production_influence": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return attempts_path, summary_path


def _probe_attempt(
    *,
    client: _HttpSession,
    year: int,
    variant_id: str,
    params: dict[str, str],
    raw_root: Path,
    headers: dict[str, str],
    timeout_seconds: float,
) -> Pre2016HolidayApiProbeAttempt:
    request_url = f"{_NSE_HOLIDAY_API}?{urlencode(params)}"
    try:
        response = client.get(
            _NSE_HOLIDAY_API,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
        )
        raw = response.content
        digest = hashlib.sha256(raw).hexdigest()
        content_type = str(response.headers.get("Content-Type") or "")
        suffix = ".json" if "json" in content_type.lower() else ".txt"
        raw_path = (
            raw_root
            / str(year)
            / f"{variant_id.lower()}_{digest[:12]}{suffix}"
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists() and raw_path.read_bytes() != raw:
            raise Pre2016ExternalValidationError(
                "PRE2016_API_RAW_IMMUTABILITY_VIOLATION"
            )
        raw_path.write_bytes(raw)

        payload_state = "HTTP_NON_200"
        cm_rows: list[object] = []
        dates: tuple[date, ...] = ()
        error: str | None = None
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                payload_state = "INVALID_JSON"
                error = f"{type(exc).__name__}: {exc}"
            else:
                if isinstance(payload, dict) and isinstance(payload.get("CM"), list):
                    cm_rows = list(payload["CM"])
                    dates = tuple(
                        parsed
                        for parsed in (_payload_date(row) for row in cm_rows)
                        if parsed is not None
                    )
                    payload_state = "CM_PAYLOAD"
                else:
                    payload_state = "CM_LIST_MISSING"

        covered_years = tuple(sorted({item.year for item in dates}))
        in_year_count = sum(item.year == year for item in dates)
        out_of_year_count = len(dates) - in_year_count
        accepted = (
            response.status_code == 200
            and payload_state == "CM_PAYLOAD"
            and bool(dates)
            and covered_years == (year,)
            and in_year_count == len(cm_rows)
        )
        return Pre2016HolidayApiProbeAttempt(
            year=year,
            variant_id=variant_id,
            request_url=request_url,
            http_status=response.status_code,
            content_type=content_type,
            response_sha256=digest,
            response_bytes=len(raw),
            payload_state=payload_state,
            cm_row_count=len(cm_rows),
            in_year_row_count=in_year_count,
            out_of_year_row_count=out_of_year_count,
            covered_years=covered_years,
            accepted_as_official_year_source=accepted,
            raw_path=str(raw_path),
            error=error,
        )
    except (OSError, requests.RequestException, Pre2016ExternalValidationError) as exc:
        return Pre2016HolidayApiProbeAttempt(
            year=year,
            variant_id=variant_id,
            request_url=request_url,
            http_status=None,
            content_type="",
            response_sha256=None,
            response_bytes=0,
            payload_state="REQUEST_FAILED",
            cm_row_count=0,
            in_year_row_count=0,
            out_of_year_row_count=0,
            covered_years=(),
            accepted_as_official_year_source=False,
            raw_path=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def _payload_date(row: object) -> date | None:
    if not isinstance(row, dict):
        return None
    raw = row.get("tradingDate") or row.get("date")
    if not raw:
        return None
    value = str(raw).strip()
    formats = ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d")
    for pattern in formats:
        try:
            if pattern == "%Y-%m-%d":
                return date.fromisoformat(value)
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _validate_years(years: tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(years)))
    allowed = set(range(DSI010_EXTERNAL_START.year, DSI010_EXTERNAL_END.year + 1))
    if not normalized or not set(normalized).issubset(allowed):
        raise Pre2016ExternalValidationError("PRE2016_API_PROBE_YEAR_INVALID")
    return normalized


__all__ = [
    "Pre2016HolidayApiProbeAttempt",
    "Pre2016HolidayApiProbeResult",
    "export_pre2016_holiday_api_probe",
    "probe_pre2016_holiday_api",
]
