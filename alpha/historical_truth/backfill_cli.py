from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.backfill import HistoricalBackfillEngine
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

backfill_app = typer.Typer(
    help=(
        "Run the checkpointed HTR-007 NSE cash-market backfill. "
        "Outputs remain uncertified until official session reconciliation."
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


@backfill_app.callback()
def backfill() -> None:
    """Coordinate governed historical-data population commands."""


@backfill_app.command("run")
def run_backfill(
    end: str = typer.Option(..., "--end", help="Inclusive backfill cutoff date."),
    start: str = typer.Option("2016-01-01", "--start"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/htr007_backfill"),
        "--output-dir",
    ),
    workers: int = typer.Option(
        4,
        "--workers",
        min=1,
        help="Bounded concurrent archive download workers.",
    ),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
    ),
) -> None:
    """Download, validate, ingest, snapshot, checkpoint, and report the window."""

    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )

    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalBackfillEngine(archive, canonical, snapshots)
    report = engine.run(
        start_date,
        end_date,
        workers=workers,
        retry_failed=retry_failed,
    )
    paths = engine.export(report, output_dir)

    print(f"Run Complete: {report.run_complete}")
    print(f"Operationally Complete: {report.operationally_complete}")
    print(f"Certification State: {report.certification_state.value}")
    print(f"Planning Basis: {report.planning_basis}")
    print(f"Candidate Dates: {report.candidate_date_count}")
    print(f"Complete: {report.complete_count}")
    print(f"Unavailable: {report.unavailable_count}")
    print(f"Failed: {report.failed_count}")
    print(f"Skipped: {report.skipped_count}")
    print(f"Report SHA-256: {report.report_sha256}")
    for path in paths:
        print(path)

    if (
        not report.run_complete
        or report.failed_count
        or report.skipped_count
        or report.deferred_count
    ):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    backfill_app()
