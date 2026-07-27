"""Non-certifying partial calendar audit for DSI-010 official sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    OfficialSessionCalendarEngine,
    SessionCalendarRecord,
    SessionCalendarReport,
)

from .pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    Pre2016ExternalValidationError,
)


@dataclass(frozen=True, slots=True)
class Pre2016PartialCalendarAudit:
    """Partial calendar report and review rows; never a certification."""

    report: SessionCalendarReport
    covered_years: tuple[int, ...]
    missing_years: tuple[int, ...]
    conflict_rows: tuple[dict[str, object], ...]
    unresolved_rows: tuple[dict[str, object], ...]
    manifest_unavailable_rows: tuple[dict[str, object], ...]


def audit_pre2016_calendar_partial(
    *,
    database: Path,
    manifest: Path,
    official_sources: tuple[Path, ...],
    start: date = DSI010_EXTERNAL_START,
    end: date = DSI010_EXTERNAL_END,
) -> Pre2016PartialCalendarAudit:
    """Reconcile any official-year subset without granting certification."""

    if start != DSI010_EXTERNAL_START or end != DSI010_EXTERNAL_END:
        raise Pre2016ExternalValidationError("PRE2016_PARTIAL_CALENDAR_PERIOD_MISMATCH")
    if not database.is_file():
        raise Pre2016ExternalValidationError("PRE2016_PARTIAL_CALENDAR_DATABASE_MISSING")
    if not manifest.is_file():
        raise Pre2016ExternalValidationError("PRE2016_PARTIAL_CALENDAR_MANIFEST_MISSING")
    if not official_sources:
        raise Pre2016ExternalValidationError("PRE2016_PARTIAL_CALENDAR_SOURCES_MISSING")

    sources = tuple(
        OfficialSessionCalendarEngine.load_source(path) for path in official_sources
    )
    covered_years = tuple(
        sorted({year for source in sources for year in source.covered_years})
    )
    allowed_years = set(range(start.year, end.year + 1))
    if not set(covered_years).issubset(allowed_years):
        raise Pre2016ExternalValidationError(
            "PRE2016_PARTIAL_CALENDAR_SOURCE_YEAR_OUTSIDE_PERIOD"
        )
    missing_years = tuple(sorted(allowed_years - set(covered_years)))

    canonical = CanonicalPointInTimeWarehouse(database)
    report = OfficialSessionCalendarEngine(canonical).reconcile(start, end, sources)

    conflict_rows = tuple(
        _record_row(record)
        for record in report.records
        if "HOLIDAY_HAS_OBSERVED_CANDLES" in record.issue_codes
    )
    unresolved_rows = tuple(
        _record_row(record)
        for record in report.records
        if record.trading_date.year in covered_years
        and record.classification.value == "unresolved_weekday"
    )

    latest = _latest_manifest_rows(manifest, start=start, end=end)
    record_by_date = {record.trading_date: record for record in report.records}
    manifest_rows: list[dict[str, object]] = []
    for trading_date in sorted(latest):
        payload = latest[trading_date]
        status = str(payload.get("status") or "UNKNOWN").strip().lower()
        if status != "unavailable" or trading_date.year not in covered_years:
            continue
        record = record_by_date[trading_date]
        manifest_rows.append(
            {
                "trading_date": trading_date,
                "calendar_year": trading_date.year,
                "calendar_classification": record.classification.value,
                "observed_candles": record.observed_candles,
                "official_holiday_match": record.classification.value == "holiday",
                "issue_codes": ";".join(record.issue_codes),
                "manifest_error": str(payload.get("error") or ""),
                "archive_source_url": str(payload.get("source_url") or ""),
            }
        )

    return Pre2016PartialCalendarAudit(
        report=report,
        covered_years=covered_years,
        missing_years=missing_years,
        conflict_rows=conflict_rows,
        unresolved_rows=unresolved_rows,
        manifest_unavailable_rows=tuple(manifest_rows),
    )


def _record_row(record: SessionCalendarRecord) -> dict[str, object]:
    return {
        "trading_date": record.trading_date,
        "calendar_year": record.trading_date.year,
        "classification": record.classification.value,
        "observed_candles": record.observed_candles,
        "description": record.description or "",
        "source_ids": ";".join(record.source_ids),
        "issue_codes": ";".join(record.issue_codes),
    }


def _latest_manifest_rows(
    manifest: Path,
    *,
    start: date,
    end: date,
) -> dict[date, dict[str, object]]:
    latest: dict[date, dict[str, object]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            trading_date = date.fromisoformat(str(payload.get("trading_date") or ""))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if start <= trading_date <= end:
            latest[trading_date] = payload
    return latest


__all__ = ["Pre2016PartialCalendarAudit", "audit_pre2016_calendar_partial"]
