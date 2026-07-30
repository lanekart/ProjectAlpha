"""Governed calendar certification for the DSI-010 external era."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    OfficialSessionCalendarEngine,
    SessionCalendarReport,
)

from .pre2016_calendar_sources import validate_hash_bound_official_calendar_source
from .pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    Pre2016ExternalValidationError,
)

DSI010_CALENDAR_CONTRACT_VERSION = "DSI-010-CALENDAR-v1.0.0"


@dataclass(frozen=True, slots=True)
class Pre2016CalendarCertification:
    """Calendar report plus archive-manifest reconciliation evidence."""

    report: SessionCalendarReport
    manifest_rows: tuple[dict[str, Any], ...]
    annual_rows: tuple[dict[str, Any], ...]
    manifest_unavailable_count: int
    manifest_unresolved_count: int
    manifest_holiday_match_count: int
    manifest_status_case_normalized: bool


def certify_pre2016_calendar(
    *,
    database: Path,
    manifest: Path,
    official_sources: tuple[Path, ...],
    start: date = DSI010_EXTERNAL_START,
    end: date = DSI010_EXTERNAL_END,
) -> Pre2016CalendarCertification:
    """Reconcile official calendar sources, candles, and archive-manifest states."""

    _validate_period(start, end)
    if not database.is_file():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_DATABASE_MISSING")
    if not manifest.is_file():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_MANIFEST_MISSING")
    if not official_sources:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_CALENDAR_SOURCES_MISSING"
        )

    for source_path in official_sources:
        validate_hash_bound_official_calendar_source(
            source_path,
            require_capital_market_scope=True,
        )
    sources = tuple(
        OfficialSessionCalendarEngine.load_source(path) for path in official_sources
    )
    covered_years = {year for source in sources for year in source.covered_years}
    required_years = set(range(start.year, end.year + 1))
    missing_years = sorted(required_years - covered_years)
    if missing_years:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_CALENDAR_YEARS_MISSING:"
            + ",".join(str(year) for year in missing_years)
        )

    canonical = CanonicalPointInTimeWarehouse(database)
    engine = OfficialSessionCalendarEngine(canonical)
    report = engine.reconcile(start, end, sources)
    latest = _latest_manifest_rows(manifest, start=start, end=end)
    record_by_date = {record.trading_date: record for record in report.records}

    manifest_rows: list[dict[str, Any]] = []
    unavailable_count = 0
    unresolved_count = 0
    holiday_match_count = 0
    normalized = False

    for trading_date in sorted(latest):
        payload = latest[trading_date]
        raw_status = str(payload.get("status") or "UNKNOWN")
        status = raw_status.strip().lower()
        normalized = normalized or status != raw_status
        record = record_by_date.get(trading_date)
        classification = None if record is None else record.classification.value
        official_holiday_match = status == "unavailable" and classification == "holiday"
        unresolved = status == "unavailable" and classification != "holiday"
        unavailable_count += int(status == "unavailable")
        holiday_match_count += int(official_holiday_match)
        unresolved_count += int(unresolved)
        manifest_rows.append(
            {
                "trading_date": trading_date,
                "manifest_status_raw": raw_status,
                "manifest_status_normalized": status,
                "calendar_classification": classification,
                "observed_candles": (
                    False if record is None else record.observed_candles
                ),
                "official_holiday_match": official_holiday_match,
                "unresolved_archive_unavailable": unresolved,
                "manifest_error": payload.get("error"),
                "source_url": payload.get("source_url"),
                "relative_path": payload.get("relative_path"),
            }
        )

    annual_rows = tuple(
        {
            **asdict(summary),
            "year": summary.year,
        }
        for summary in report.annual_summaries
    )
    return Pre2016CalendarCertification(
        report=report,
        manifest_rows=tuple(manifest_rows),
        annual_rows=annual_rows,
        manifest_unavailable_count=unavailable_count,
        manifest_unresolved_count=unresolved_count,
        manifest_holiday_match_count=holiday_match_count,
        manifest_status_case_normalized=normalized,
    )


def export_pre2016_calendar_certification(
    result: Pre2016CalendarCertification,
    output: Path,
    *,
    database: Path,
) -> tuple[Path, ...]:
    """Export the standard governed calendar report plus DSI-010 audit evidence."""

    output.mkdir(parents=True, exist_ok=True)
    engine = OfficialSessionCalendarEngine(CanonicalPointInTimeWarehouse(database))
    paths = list(engine.export(result.report, output))

    manifest_path = output / "dsi010_pre2016_calendar_manifest_audit.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = (
            tuple(result.manifest_rows[0])
            if result.manifest_rows
            else (
                "trading_date",
                "manifest_status_raw",
                "manifest_status_normalized",
                "calendar_classification",
                "observed_candles",
                "official_holiday_match",
                "unresolved_archive_unavailable",
                "manifest_error",
                "source_url",
                "relative_path",
            )
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.manifest_rows:
            writer.writerow(_jsonable(row))

    annual_path = output / "dsi010_pre2016_calendar_annual_summary.csv"
    with annual_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = tuple(result.annual_rows[0]) if result.annual_rows else ("year",)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.annual_rows:
            writer.writerow(_jsonable(row))

    summary = {
        "contract_version": DSI010_CALENDAR_CONTRACT_VERSION,
        "calendar_report_sha256": result.report.report_sha256,
        "certification_state": result.report.certification_state.value,
        "start_date": result.report.start_date.isoformat(),
        "end_date": result.report.end_date.isoformat(),
        "expected_sessions": result.report.expected_session_count,
        "observed_sessions": result.report.observed_session_count,
        "official_holidays": result.report.official_holiday_count,
        "official_special_sessions": result.report.official_special_session_count,
        "unresolved_weekdays": result.report.unresolved_weekday_count,
        "unconfirmed_special_sessions": result.report.unconfirmed_special_session_count,
        "missing_special_sessions": result.report.missing_special_session_count,
        "conflicts": result.report.conflict_count,
        "manifest_unavailable_count": result.manifest_unavailable_count,
        "manifest_holiday_match_count": result.manifest_holiday_match_count,
        "manifest_unresolved_count": result.manifest_unresolved_count,
        "manifest_status_case_normalized": result.manifest_status_case_normalized,
        "production_influence": False,
    }
    summary_path = output / "dsi010_pre2016_calendar_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.extend((manifest_path, annual_path, summary_path))
    return tuple(paths)


def validate_pre2016_calendar_report(
    report_path: Path,
    *,
    require_certified: bool = True,
) -> dict[str, Any]:
    """Validate a calendar report before DSI-010 consumes market data."""

    if not report_path.is_file():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REPORT_MISSING")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REPORT_INVALID") from exc
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REPORT_INVALID")
    expected_hash = payload.get("report_sha256")
    without_hash = dict(payload)
    without_hash.pop("report_sha256", None)
    observed_hash = hashlib.sha256(
        json.dumps(without_hash, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected_hash != observed_hash:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REPORT_HASH_MISMATCH")
    if payload.get("start_date") != DSI010_EXTERNAL_START.isoformat():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_START_MISMATCH")
    if payload.get("end_date") != DSI010_EXTERNAL_END.isoformat():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_END_MISMATCH")
    if require_certified and payload.get("certification_state") != "certified":
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_NOT_CERTIFIED")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_SOURCE_REGISTRY_EMPTY")
    for row in sources:
        if not isinstance(row, dict):
            raise Pre2016ExternalValidationError("PRE2016_CALENDAR_SOURCE_INVALID")
        source_path = Path(str(row.get("source_path") or ""))
        if not source_path.is_file():
            raise Pre2016ExternalValidationError("PRE2016_CALENDAR_SOURCE_FILE_MISSING")
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != str(
            row.get("source_sha256") or ""
        ):
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_SOURCE_HASH_MISMATCH"
            )
    if int(payload.get("unresolved_weekday_count") or 0) != 0:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_UNRESOLVED_WEEKDAYS")
    if int(payload.get("unconfirmed_special_session_count") or 0) != 0:
        raise Pre2016ExternalValidationError(
            "PRE2016_CALENDAR_UNCONFIRMED_SPECIAL_SESSIONS"
        )
    if int(payload.get("missing_special_session_count") or 0) != 0:
        raise Pre2016ExternalValidationError(
            "PRE2016_CALENDAR_MISSING_SPECIAL_SESSIONS"
        )
    if int(payload.get("conflict_count") or 0) != 0:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_CONFLICTS")
    return payload


def _latest_manifest_rows(
    manifest: Path,
    *,
    start: date,
    end: date,
) -> dict[date, dict[str, Any]]:
    latest: dict[date, dict[str, Any]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            trading_date = date.fromisoformat(str(payload.get("trading_date")))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if start <= trading_date <= end:
            latest[trading_date] = payload
    return latest


def _validate_period(start: date, end: date) -> None:
    if start != DSI010_EXTERNAL_START or end != DSI010_EXTERNAL_END:
        raise Pre2016ExternalValidationError(
            "PRE2016_CALENDAR_PERIOD_MUST_MATCH_FROZEN_EXTERNAL_ERA"
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


__all__ = [
    "DSI010_CALENDAR_CONTRACT_VERSION",
    "Pre2016CalendarCertification",
    "certify_pre2016_calendar",
    "export_pre2016_calendar_certification",
    "validate_pre2016_calendar_report",
]
