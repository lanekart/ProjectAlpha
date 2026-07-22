"""CLI for HTR-010B1D1 bridge forensics."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.factor_transformation_bridge_forensics import (
    FactorTransformationBridgeForensicsEngine,
)


def factor_transformation_bridge_forensics(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    htr010b_output: Path = typer.Option(
        Path("artifacts/htr010b_complete_corporate_action_dataset"),
        "--htr010b-output",
        exists=True,
        file_okay=False,
    ),
    htr010b1d_output: Path = typer.Option(
        Path("artifacts/htr010b1d_factor_transformation_forensics_2026"),
        "--htr010b1d-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1d1_cross_series_identity_bridge"),
        "--output",
    ),
) -> None:
    """Reconstruct governed pre/post candle bridges for B1D cases."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    report = FactorTransformationBridgeForensicsEngine().run(
        database_path=database,
        htr010b_output=htr010b_output,
        htr010b1d_output=htr010b1d_output,
        start_date=start_date,
        end_date=end_date,
    )
    paths = FactorTransformationBridgeForensicsEngine.export(report, output)
    print("HTR-010B1D1 Cross-Series and Identity-Bridge Forensics")
    print(f"Cases audited: {report['case_count']:,}")
    print(f"Classifications: {report['classification_counts']}")
    print(f"Recommended repairs: {report['recommended_repair_action_counts']}")
    print(
        "Cross-series pairing artifacts: "
        f"{report['cross_series_pairing_artifact_count']:,}"
    )
    print(
        f"Governed cross-ISIN bridges: {report['governed_cross_isin_bridge_count']:,}"
    )
    print(
        "Non-comparable identity transitions: "
        f"{report['identity_transition_noncomparable_count']:,}"
    )
    print(f"Missing candle-lineage bridges: {report['candle_lineage_missing_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["factor_transformation_bridge_forensics"]
