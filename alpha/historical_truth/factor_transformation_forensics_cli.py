"""CLI for HTR-010B1D factor-transformation forensics."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.factor_transformation_forensics import (
    FactorTransformationForensicsEngine,
)


def factor_transformation_forensics(
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
    htr010b1c_output: Path = typer.Option(
        Path("artifacts/htr010b1c_observed_2026_after_htr007c"),
        "--htr010b1c-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1d_factor_transformation_forensics"),
        "--output",
    ),
) -> None:
    """Attribute residual factor defects without changing factors or admission."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    try:
        report = FactorTransformationForensicsEngine().run(
            database_path=database,
            htr010b_output=htr010b_output,
            htr010b1c_output=htr010b1c_output,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    paths = FactorTransformationForensicsEngine.export(report, output)
    print("HTR-010B1D Factor Transformation Forensics")
    print(f"Cases audited: {report['case_count']:,}")
    print(f"Classifications: {report['classification_counts']}")
    print(f"Recommended repairs: {report['recommended_repair_action_counts']}")
    print(f"Orientation candidates: {report['orientation_candidate_count']:,}")
    print(f"Term arithmetic mismatches: {report['term_arithmetic_mismatch_count']:,}")
    print(f"Series mismatches: {report['series_selection_mismatch_count']:,}")
    print(f"Series ambiguities: {report['series_selection_ambiguity_count']:,}")
    print(f"Event-date mismatches: {report['date_basis_mismatch_count']:,}")
    print(f"Unresolved forensic cases: {report['unresolved_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["factor_transformation_forensics"]
