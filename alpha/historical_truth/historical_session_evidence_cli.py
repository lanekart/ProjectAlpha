from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.historical_session_evidence import (
    HistoricalEvidenceStatus,
    HistoricalSessionEvidenceEngine,
)
from alpha.historical_truth.session_calendar import OfficialSessionCalendarEngine

historical_session_evidence_app = typer.Typer(
    help=(
        "Acquire immutable annual NSE CM session circulars and reconcile "
        "historical trading sessions."
    ),
    no_args_is_help=True,
)


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _progress(label: str, current: int, total: int, detail: str = "") -> None:
    width = 36
    total = max(total, 1)
    current = min(current, total)
    filled = int(width * current / total)
    percent = int(100 * current / total)
    suffix = f" | {detail}" if detail else ""
    print(
        f"\r{label} [{'#' * filled}{'-' * (width - filled)}] "
        f"{percent:3d}% ({current}/{total}){suffix}",
        end="" if current < total else "\n",
        flush=True,
    )


@historical_session_evidence_app.callback()
def historical_session_evidence() -> None:
    """Coordinate governed historical-session evidence commands."""


@historical_session_evidence_app.command("run")
def run(
    end_year: int = typer.Option(2025, "--end-year", min=1994),
    start_year: int = typer.Option(2016, "--start-year", min=1994),
    end: str = typer.Option("2026-07-20", "--end"),
    start: str = typer.Option("2016-01-01", "--start"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/htr007_historical_session_evidence"),
        "--output-dir",
    ),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
) -> None:
    """Acquire annual circulars, normalize them, and reconcile the full window."""

    if start_year > end_year:
        raise typer.BadParameter(
            "must be on or before --end-year",
            param_hint="--start-year",
        )
    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )

    acquisition = HistoricalSessionEvidenceEngine(root)
    years_total = end_year - start_year + 1
    _progress("Annual NSE evidence", 0, years_total, f"starting {start_year}")
    evidence_report = acquisition.acquire_range(
        start_year,
        end_year,
        timeout_seconds=timeout_seconds,
        progress=lambda current, total, year: _progress(
            "Annual NSE evidence",
            current,
            total,
            str(year),
        ),
    )
    evidence_paths = acquisition.export(evidence_report, output_dir)

    calendar_source_paths = list(
        acquisition.normalized_source_paths(evidence_report.records)
    )
    current_source_dir = root / "raw" / "nse" / "calendar"
    calendar_source_paths.extend(
        path
        for path in sorted(current_source_dir.glob("nse_cm_holidays_*.json"))
        if path.parent == current_source_dir
    )
    unique_paths = tuple(dict.fromkeys(path.resolve() for path in calendar_source_paths))
    if not unique_paths:
        raise typer.BadParameter("no official calendar sources are available")

    sources = []
    for index, path in enumerate(unique_paths, start=1):
        sources.append(OfficialSessionCalendarEngine.load_source(path))
        _progress("Official source loading", index, len(unique_paths), path.name)

    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    calendar = OfficialSessionCalendarEngine(canonical)
    _progress("Session reconciliation", 0, 1, "full window")
    calendar_report = calendar.reconcile(start_date, end_date, sources)
    calendar_paths = calendar.export(calendar_report, output_dir)
    _progress("Session reconciliation", 1, 1, "complete")

    print(f"Evidence Complete: {evidence_report.complete_count}")
    print(f"Evidence Reused: {evidence_report.reused_count}")
    print(f"Evidence Failed: {evidence_report.failed_count}")
    print(f"Historical Holidays Parsed: {evidence_report.holiday_count}")
    print(
        "Historical Special Sessions Parsed: "
        f"{evidence_report.special_session_count}"
    )
    print(f"Evidence Report SHA-256: {evidence_report.report_sha256}")
    print(f"Certification State: {calendar_report.certification_state.value}")
    print(f"Official Sources: {len(calendar_report.sources)}")
    print(f"Official Holidays: {calendar_report.official_holiday_count}")
    print(
        "Official Special Sessions: "
        f"{calendar_report.official_special_session_count}"
    )
    print(f"Expected Sessions: {calendar_report.expected_session_count}")
    print(f"Observed Sessions: {calendar_report.observed_session_count}")
    print(f"Unresolved Weekdays: {calendar_report.unresolved_weekday_count}")
    print(
        "Unconfirmed Special Sessions: "
        f"{calendar_report.unconfirmed_special_session_count}"
    )
    print(
        "Missing Special Sessions: "
        f"{calendar_report.missing_special_session_count}"
    )
    print(f"Conflicts: {calendar_report.conflict_count}")
    print(f"Calendar Report SHA-256: {calendar_report.report_sha256}")
    for path in (*evidence_paths, *calendar_paths):
        print(path)

    failed_years = tuple(
        record.year
        for record in evidence_report.records
        if record.status is HistoricalEvidenceStatus.FAILED
    )
    if failed_years:
        print(f"FAILED YEARS: {', '.join(str(year) for year in failed_years)}")
    if (
        evidence_report.failed_count
        or calendar_report.conflict_count
        or calendar_report.missing_special_session_count
    ):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    historical_session_evidence_app()
