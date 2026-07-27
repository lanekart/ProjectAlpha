"""Artifacts for the non-certifying DSI-010 partial calendar audit."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from .pre2016_calendar_partial import Pre2016PartialCalendarAudit


def export_pre2016_partial_calendar_audit(
    result: Pre2016PartialCalendarAudit,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic review artifacts without granting certification."""

    output.mkdir(parents=True, exist_ok=True)
    conflict_path = output / "dsi010_pre2016_partial_calendar_conflicts.csv"
    unresolved_path = output / "dsi010_pre2016_partial_calendar_unresolved.csv"
    manifest_path = output / "dsi010_pre2016_partial_calendar_manifest.csv"
    annual_path = output / "dsi010_pre2016_partial_calendar_annual.csv"
    summary_path = output / "dsi010_pre2016_partial_calendar_summary.json"

    _write_csv(conflict_path, result.conflict_rows)
    _write_csv(unresolved_path, result.unresolved_rows)
    _write_csv(manifest_path, result.manifest_unavailable_rows)
    _write_csv(
        annual_path,
        tuple(
            {
                "year": row.year,
                "official_source_covered": row.official_source_covered,
                "official_weekday_holidays": row.official_weekday_holidays,
                "official_special_sessions": row.official_special_sessions,
                "expected_sessions": row.expected_sessions,
                "observed_sessions": row.observed_sessions,
                "unresolved_weekdays": row.unresolved_weekdays,
                "unconfirmed_special_sessions": row.unconfirmed_special_sessions,
                "missing_special_sessions": row.missing_special_sessions,
                "conflicts": row.conflicts,
            }
            for row in result.report.annual_summaries
        ),
    )

    summary = {
        "start_date": result.report.start_date.isoformat(),
        "end_date": result.report.end_date.isoformat(),
        "certification_state": result.report.certification_state.value,
        "covered_years": list(result.covered_years),
        "missing_years": list(result.missing_years),
        "official_holiday_count": result.report.official_holiday_count,
        "official_special_session_count": result.report.official_special_session_count,
        "observed_session_count": result.report.observed_session_count,
        "conflict_count": len(result.conflict_rows),
        "covered_year_unresolved_count": len(result.unresolved_rows),
        "covered_year_manifest_unavailable_count": len(
            result.manifest_unavailable_rows
        ),
        "calendar_certification_permitted": False,
        "production_influence": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return (
        conflict_path,
        unresolved_path,
        manifest_path,
        annual_path,
        summary_path,
    )


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    fieldnames = tuple(rows[0]) if rows else ("trading_date",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: value.isoformat() if isinstance(value, date) else value
                    for key, value in row.items()
                }
            )


__all__ = ["export_pre2016_partial_calendar_audit"]
