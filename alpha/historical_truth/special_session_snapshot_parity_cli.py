from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine
from alpha.historical_truth.special_session_snapshot_parity import (
    SpecialSessionSnapshotParityEngine,
)


def _date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _progress(current: int, total: int, trading_date: date) -> None:
    width = 36
    bounded_total = max(total, 1)
    filled = int(width * current / bounded_total)
    line = (
        "Snapshot parity "
        f"[{'#' * filled}{'-' * (width - filled)}] "
        f"{int(100 * current / bounded_total):3d}% "
        f"({current}/{bounded_total}) | {trading_date}"
    )
    if sys.stdout.isatty():
        print(
            f"\r\x1b[2K{line}",
            end="" if current < total else "\n",
            flush=True,
        )
    else:
        print(line, flush=True)


def special_session_snapshot_repair(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    snapshot_root: Path = typer.Option(
        Path("alpha_data/snapshots"),
        "--snapshot-root",
    ),
    calendar_report: Path = typer.Option(
        ...,
        "--calendar-report",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr007c_special_session_snapshot_parity"),
        "--output",
    ),
    selected_date: list[str] = typer.Option(
        [],
        "--date",
        help="Official special-session date; repeat to filter repair targets.",
    ),
    verify_only: bool = typer.Option(False, "--verify-only"),
) -> None:
    """Audit and repair immutable snapshots for official special sessions."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    canonical = CanonicalPointInTimeWarehouse(database)
    snapshots = PointInTimeSnapshotEngine(canonical, snapshot_root)
    engine = SpecialSessionSnapshotParityEngine(canonical, snapshots)
    try:
        report = engine.run(
            calendar_report,
            start_date=start_date,
            end_date=end_date,
            selected_dates=tuple(_date(value, "--date") for value in selected_date),
            verify_only=verify_only,
            progress=_progress,
        )
    except ValueError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="--calendar-report",
        ) from exc
    paths = engine.export(report, output)
    summary = report.summary
    print(f"Canonical Observed Dates: {summary.canonical_observed_dates}")
    print(f"Expected Snapshots: {summary.snapshot_files_expected}")
    print(f"Present Snapshots: {summary.snapshot_files_present}")
    print(f"Missing Snapshots: {len(summary.missing_snapshot_dates)}")
    print(f"Invalid Snapshots: {len(summary.invalid_snapshot_dates)}")
    print(f"Orphan Snapshots: {len(summary.orphan_snapshot_dates)}")
    print(
        "Special-Session Snapshots: "
        f"{summary.official_special_session_snapshots_valid}/"
        f"{summary.official_special_session_snapshots_expected} valid"
    )
    print(f"Final Parity State: {summary.final_parity_state.value}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    for record in report.records:
        failure = (
            record.snapshot_failure_code.value if record.snapshot_failure_code else "OK"
        )
        print(
            f"{record.trading_date} | {record.snapshot_status.value} | "
            f"rows={record.canonical_row_count} | "
            f"{failure}"
        )
    for path in paths:
        print(path)
    if not report.complete:
        raise typer.Exit(code=1)
