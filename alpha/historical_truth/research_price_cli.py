"""CLI for the DSI-011A complete research-price table."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.research_price_table import (
    ResearchPriceTableBuilder,
    export_research_price_certification,
)


def research_price_certify(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option(..., "--end"),
    output: Path = typer.Option(
        Path("artifacts/dsi011a_post2016_execution/research_price"),
        "--output",
    ),
) -> None:
    """Build and certify complete governed post-2016 research prices."""

    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from exc
    report = ResearchPriceTableBuilder().build(
        database,
        start_date=start_date,
        end_date=end_date,
    )
    paths = export_research_price_certification(report, output)
    print("DSI-011A Complete Research Price Table")
    print(f"Certified range: {report.start_date} to {report.end_date}")
    print(f"Sessions: {report.observed_sessions}")
    print(f"Eligible securities: {report.eligible_securities}")
    print(f"Total NSE rows: {report.total_raw_rows}")
    print(f"Eligible rows: {report.eligible_raw_rows}")
    print(f"Ineligible non-equity rows: {report.ineligible_non_equity_rows}")
    print(
        "Preserved separate identity boundaries: "
        f"{report.preserved_separate_identity_boundaries}"
    )
    print(f"Research rows: {report.research_rows}")
    print(f"Unexplained missing rows: {report.unexplained_missing_rows}")
    print(f"Invalid adjusted OHLC rows: {report.invalid_adjusted_ohlc_rows}")
    print(f"Readiness: {report.readiness_state}")
    print(f"Logical SHA-256: {report.logical_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {', '.join(str(path) for path in paths)}")


__all__ = ["research_price_certify"]
