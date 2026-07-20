from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth import HistoricalTruthWarehouse

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
