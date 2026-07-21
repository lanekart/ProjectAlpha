from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import typer
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.historical_session_evidence import (
    HistoricalEvidenceReport,
    HistoricalEvidenceStatus,
)
from alpha.historical_truth.historical_session_evidence_audit import (
    HistoricalSessionEvidenceRepairEngine,
)
from alpha.historical_truth.session_calendar import (
    OfficialCalendarSource,
    OfficialSessionCalendarEngine,
    SessionCalendarReport,
)

historical_session_evidence_app = typer.Typer(
    help=(
        "Acquire immutable annual NSE CM session evidence, audit official-source "
        "admission, and reconcile historical trading sessions."
    ),
    no_args_is_help=True,
)
_LAST_PROGRESS_WIDTH: dict[str, int] = {}


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _progress(label: str, current: int, total: int, detail: str = "") -> None:
    """Keep interactive progress and captured logs separately readable."""

    total = max(total, 1)
    current = min(max(current, 0), total)
    suffix = f" | {detail}" if detail else ""
    if not sys.stdout.isatty():
        typer.echo(f"{label}: {current}/{total}{suffix}")
        return
    width = 36
    filled = int(width * current / total)
    percent = int(100 * current / total)
    rendered = (
        f"{label} [{'#' * filled}{'-' * (width - filled)}] "
        f"{percent:3d}% ({current}/{total}){suffix}"
    )
    previous = _LAST_PROGRESS_WIDTH.get(label, 0)
    print(
        f"\r{rendered}{' ' * max(0, previous - len(rendered))}",
        end="" if current < total else "\n",
        flush=True,
    )
    _LAST_PROGRESS_WIDTH[label] = len(rendered)


@historical_session_evidence_app.callback()
def historical_session_evidence() -> None:
    """Coordinate governed historical-session evidence commands."""


def _validate_years(start_year: int, end_year: int) -> None:
    if start_year > end_year:
        raise typer.BadParameter(
            "must be on or before --end-year",
            param_hint="--start-year",
        )


def _validate_dates(start: str, end: str) -> tuple[date, date]:
    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    return start_date, end_date


def _calendar_sources(
    acquisition: HistoricalSessionEvidenceRepairEngine,
    evidence_report: HistoricalEvidenceReport,
    root: Path,
) -> tuple[OfficialCalendarSource, ...]:
    paths = list(acquisition.normalized_source_paths(evidence_report.records))
    current_source_dir = root / "raw" / "nse" / "calendar"
    paths.extend(
        path
        for path in sorted(current_source_dir.glob("nse_cm_holidays_*.json"))
        if path.parent == current_source_dir
    )
    unique_paths = tuple(dict.fromkeys(path.resolve() for path in paths))
    if not unique_paths:
        raise typer.BadParameter("no official calendar sources are available")
    sources: list[OfficialCalendarSource] = []
    for index, path in enumerate(unique_paths, start=1):
        sources.append(OfficialSessionCalendarEngine.load_source(path))
        _progress("Official source loading", index, len(unique_paths), path.name)
    return tuple(sources)


def _reconcile(
    *,
    acquisition: HistoricalSessionEvidenceRepairEngine,
    evidence_report: HistoricalEvidenceReport,
    root: Path,
    output_dir: Path,
    start_date: date,
    end_date: date,
) -> tuple[SessionCalendarReport, tuple[Path, ...]]:
    sources = _calendar_sources(acquisition, evidence_report, root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    calendar = OfficialSessionCalendarEngine(canonical)
    _progress("Session reconciliation", 0, 1, "full window")
    report = calendar.reconcile(start_date, end_date, sources)
    calendar_paths = calendar.export(report, output_dir)
    unresolved = acquisition.unresolved_sessions(evidence_report, report)
    unresolved_paths = acquisition.export_unresolved(unresolved, output_dir)
    _progress("Session reconciliation", 1, 1, "complete")
    return report, (*calendar_paths, *unresolved_paths)


def _print_summary(
    evidence_report: HistoricalEvidenceReport,
    calendar_report: SessionCalendarReport | None,
    paths: tuple[Path, ...],
) -> None:
    print(f"Evidence Complete: {evidence_report.complete_count}")
    print(f"Evidence Reused: {evidence_report.reused_count}")
    print(f"Evidence Failed: {evidence_report.failed_count}")
    print(f"Historical Holidays Parsed: {evidence_report.holiday_count}")
    print(
        f"Historical Special Sessions Parsed: {evidence_report.special_session_count}"
    )
    print(f"Evidence Report SHA-256: {evidence_report.report_sha256}")
    if calendar_report is not None:
        certification = HistoricalSessionEvidenceRepairEngine.certification_label(
            evidence_report, calendar_report
        )
        print(f"Certification State: {certification}")
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
            f"Missing Special Sessions: {calendar_report.missing_special_session_count}"
        )
        print(f"Conflicts: {calendar_report.conflict_count}")
        print(f"Calendar Report SHA-256: {calendar_report.report_sha256}")
    for path in paths:
        print(path)
    failed_years = tuple(
        item.year
        for item in evidence_report.records
        if item.status is HistoricalEvidenceStatus.FAILED
    )
    if failed_years:
        print(f"FAILED YEARS: {', '.join(str(year) for year in failed_years)}")


@historical_session_evidence_app.command("acquire")
def acquire(
    end_year: int = typer.Option(2025, "--end-year", min=1994),
    start_year: int = typer.Option(2016, "--start-year", min=1994),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/htr007_historical_session_evidence"),
        "--output-dir",
        "--output",
    ),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
) -> None:
    """Acquire annual evidence and emit the HTR-007A acquisition audit."""

    _validate_years(start_year, end_year)
    acquisition = HistoricalSessionEvidenceRepairEngine(root)
    years_total = end_year - start_year + 1
    _progress("Annual NSE evidence", 0, years_total, f"starting {start_year}")
    evidence_report, audit_report = acquisition.acquire_range_with_audit(
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
    paths = (
        *acquisition.export(evidence_report, output_dir),
        *acquisition.export_audit(audit_report, output_dir),
    )
    _print_summary(evidence_report, None, paths)
    if evidence_report.failed_count:
        raise typer.Exit(code=1)


@historical_session_evidence_app.command("audit")
def audit(
    evidence_dir: Path = typer.Option(
        Path("artifacts/htr007_historical_session_evidence"),
        "--evidence-dir",
    ),
) -> None:
    """Inspect a previously generated deterministic HTR-007A audit."""

    path = evidence_dir / "htr007a_acquisition_audit.json"
    if not path.exists():
        raise typer.BadParameter(f"acquisition audit not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"Audit: {path}")
    print(f"Complete Years: {payload['complete_years']}")
    print(f"Reused Years: {payload['reused_years']}")
    print(f"Failed Years: {payload['failed_years']}")
    print(f"Attempts: {len(payload.get('attempts', []))}")
    rejected = sum(
        item.get("evidence_status") == "rejected"
        for item in payload.get("attempts", [])
        if isinstance(item, dict)
    )
    print(f"Rejected Evidence: {rejected}")
    print(f"Audit SHA-256: {payload['report_sha256']}")
    if int(payload["failed_years"]):
        raise typer.Exit(code=1)


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
        "--output",
    ),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
) -> None:
    """Acquire, audit, normalize, and reconcile the full historical window."""

    _validate_years(start_year, end_year)
    start_date, end_date = _validate_dates(start, end)
    acquisition = HistoricalSessionEvidenceRepairEngine(root)
    years_total = end_year - start_year + 1
    _progress("Annual NSE evidence", 0, years_total, f"starting {start_year}")
    evidence_report, audit_report = acquisition.acquire_range_with_audit(
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
    audit_paths = acquisition.export_audit(audit_report, output_dir)
    calendar_report, calendar_paths = _reconcile(
        acquisition=acquisition,
        evidence_report=evidence_report,
        root=root,
        output_dir=output_dir,
        start_date=start_date,
        end_date=end_date,
    )
    _print_summary(
        evidence_report,
        calendar_report,
        (*evidence_paths, *audit_paths, *calendar_paths),
    )
    if (
        evidence_report.failed_count
        or calendar_report.conflict_count
        or calendar_report.missing_special_session_count
        or calendar_report.unresolved_weekday_count
    ):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    historical_session_evidence_app()
