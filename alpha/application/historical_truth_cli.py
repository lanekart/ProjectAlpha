from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth import (
    CanonicalPointInTimeWarehouse,
    HistoricalPopulationEngine,
    HistoricalTruthIntegrityAudit,
    HistoricalTruthWarehouse,
    PointInTimeSnapshotEngine,
)

historical_truth_app = typer.Typer(
    help="Build and audit official historical market truth."
)


@historical_truth_app.command("init")
def initialise(
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    warehouse.initialise()
    print(f"Historical Truth Warehouse initialised: {root}")


@historical_truth_app.command("plan")
def plan(
    start: date = typer.Option(..., "--start"),
    end: date = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    requests = warehouse.plan_nse_bhavcopies(start, end)
    print(f"Planned NSE bhavcopy requests: {len(requests)}")
    for request in requests:
        print(
            f"{request.trading_date.isoformat()} | {request.source_url} | "
            f"{request.relative_path}"
        )


@historical_truth_app.command("fetch")
def fetch(
    start: date = typer.Option(..., "--start"),
    end: date = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
        help="Retry files whose latest manifest state is FAILED.",
    ),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    requests = warehouse.plan_nse_bhavcopies(start, end)
    records = warehouse.fetch_many(requests, retry_failed=retry_failed)
    for record in records:
        print(
            f"{record.trading_date.isoformat()} | {record.status.value} | "
            f"{record.relative_path}"
        )


@historical_truth_app.command("populate")
def populate(
    start: date = typer.Option(..., "--start"),
    end: date = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_population"),
        "--output-dir",
    ),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
    ),
) -> None:
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalPopulationEngine(archive, canonical, snapshots)
    requests = archive.plan_nse_bhavcopies(start, end)
    records = engine.populate(requests, retry_failed=retry_failed)
    summary = engine.summarise(records)
    paths = engine.export(records, output_dir)
    print(f"Population coverage: {summary.coverage_ratio:.2%}")
    print(f"Candle snapshots ingested: {summary.candle_snapshots}")
    print(f"Evidence-complete snapshots: {summary.evidence_complete_snapshots}")
    print(f"Evidence-incomplete snapshots: {summary.evidence_incomplete_snapshots}")
    print(f"Failed: {summary.failed}")
    print(f"Unavailable: {summary.unavailable}")
    print(f"Skipped: {summary.skipped}")
    print(f"Ingested rows: {summary.ingested_rows}")
    for path in paths:
        print(path)


@historical_truth_app.command("status")
def status(
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_truth"),
        "--output-dir",
    ),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    records = warehouse.records()
    paths = warehouse.export_status(output_dir)
    print(f"Manifest records: {len(records)}")
    for path in paths:
        print(path)


@historical_truth_app.command("validate-csv")
def validate_csv(
    csv_path: Path = typer.Argument(..., exists=True, dir_okay=False),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    issues = warehouse.validate_bhavcopy_csv(csv_path)
    if not issues:
        print("VALID")
        return
    for issue in issues:
        location = f" row={issue.row_number}" if issue.row_number else ""
        print(f"{issue.severity.value.upper()} {issue.code}{location}: {issue.message}")
    raise typer.Exit(code=1)


@historical_truth_app.command("integrity-audit")
def integrity_audit(
    start: date = typer.Option(..., "--start"),
    end: date = typer.Option(..., "--end"),
    as_of: date = typer.Option(
        ...,
        "--as-of",
        help="Deterministic knowledge cutoff.",
    ),
    holiday: list[date] = typer.Option(
        [],
        "--holiday",
        help="Explicit exchange holiday; repeat for multiple dates.",
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_truth_integrity"),
        "--output-dir",
    ),
) -> None:
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalTruthIntegrityAudit(
        archive,
        canonical,
        snapshots,
        holiday_dates=frozenset(holiday),
    )
    report = engine.audit(start, end, as_of_date=as_of)
    paths = engine.export(report, output_dir)
    summary = report.summary
    print(f"Expected trading days: {summary.expected_trading_days}")
    print(f"Observed trading days: {summary.observed_trading_days}")
    print(f"Coverage: {summary.coverage_ratio:.2%}")
    print(f"Candle replay ready: {summary.candle_replay_ready}")
    print(f"Full-evidence replay ready: {summary.full_evidence_replay_ready}")
    for blocker in report.replay_blockers:
        print(f"BLOCKER {blocker}")
    for path in paths:
        print(path)
