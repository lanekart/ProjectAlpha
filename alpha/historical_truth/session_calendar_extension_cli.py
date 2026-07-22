"""CLI for HTR-007C governed session-calendar extension."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.session_calendar import CalendarCertificationState
from alpha.historical_truth.session_calendar_extension import (
    GovernedSessionCalendarExtensionEngine,
)


def session_calendar_extend_certify(
    existing_calendar_report: Path = typer.Option(
        Path("artifacts/htr007_historical_session_evidence/htr007_session_calendar.json"),
        "--existing-calendar-report",
        exists=True,
        dir_okay=False,
    ),
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    source_dir: Path = typer.Option(
        Path("alpha_data/sources/session_calendar"),
        "--source-dir",
    ),
    current_source: Path | None = typer.Option(
        None,
        "--current-source",
        exists=True,
        dir_okay=False,
        help="Pinned official source; skips network fetch when supplied.",
    ),
    through_date: str = typer.Option("2026-07-20", "--through-date"),
    output: Path = typer.Option(
        Path("artifacts/htr007c_governed_calendar_extension_2026"),
        "--output",
    ),
    refresh: bool = typer.Option(True, "--refresh/--no-refresh"),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
) -> None:
    """Append official NSE calendar evidence through a later governed date."""

    end_date = _date(through_date)
    engine = GovernedSessionCalendarExtensionEngine()
    try:
        report, audit = engine.extend(
            existing_calendar_report=existing_calendar_report,
            database_path=database,
            source_dir=source_dir,
            through_date=end_date,
            current_source_path=current_source,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    paths = engine.export(report, audit, output, database_path=database)
    print("HTR-007C Governed Session Calendar Extension")
    print(f"Existing window end: {audit.existing_window_end}")
    print(f"Extended window end: {audit.extended_window_end}")
    print(f"Appended years: {list(audit.appended_years)}")
    print(f"Historical parity: {audit.historical_parity_state}")
    print(f"Historical parity mismatches: {audit.historical_parity_mismatch_count}")
    print(f"Certification state: {report.certification_state.value}")
    print(f"Expected sessions: {report.expected_session_count}")
    print(f"Observed sessions: {report.observed_session_count}")
    print(f"Unresolved weekdays: {report.unresolved_weekday_count}")
    print(f"Unconfirmed special sessions: {report.unconfirmed_special_session_count}")
    print(f"Missing special sessions: {report.missing_special_session_count}")
    print(f"Conflicts: {report.conflict_count}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("PRODUCTION_INFLUENCE=false")

    if audit.historical_parity_mismatch_count:
        raise typer.Exit(code=1)
    if report.certification_state is not CalendarCertificationState.CERTIFIED:
        raise typer.Exit(code=1)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use YYYY-MM-DD",
            param_hint="--through-date",
        ) from exc


__all__ = ["session_calendar_extend_certify"]
