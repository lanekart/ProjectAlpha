"""CLI for the genuine DSI-011A conversational acceptance sequence."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.research.lab_acceptance import run_dsi011a_acceptance


def research_acceptance(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    root: Path = typer.Option(
        Path(".alpha/research/dsi011a_acceptance"),
        "--root",
    ),
) -> None:
    """Run A-I and the two DSI-011A execution probes."""

    report = run_dsi011a_acceptance(database=database, root=root)
    print("DSI-011A Conversational Research Acceptance")
    print(f"Root: {report.root}")
    print(f"Experiments: {', '.join(report.experiment_ids)}")
    print(f"Completed top-level runs: {report.completed_runs}")
    print(f"Artifact logical SHA-256: {report.artifact_logical_sha256}")
    print(f"Summary: {report.summary_path}")
    print(f"Comparison: {report.comparison_path}")
    print(f"Manifest: {report.artifact_manifest_path}")
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["research_acceptance"]
