"""CLI for DSI-010B3 residual corporate-action closure certification."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.residual_corporate_action_closure import (
    ResidualCorporateActionClosureEngine,
    ResidualCorporateActionClosureExporter,
)


def residual_corporate_action_closure_certify(
    baseline_b1c_output: Path = typer.Option(
        ..., "--baseline-b1c-output", exists=True, file_okay=False
    ),
    final_b1c_output: Path = typer.Option(
        ..., "--final-b1c-output", exists=True, file_okay=False
    ),
    baseline_htr010b_output: Path = typer.Option(
        ..., "--baseline-htr010b-output", exists=True, file_okay=False
    ),
    final_htr010b_output: Path = typer.Option(
        ..., "--final-htr010b-output", exists=True, file_okay=False
    ),
    official_source_root: Path | None = typer.Option(
        None, "--official-source-root", file_okay=False
    ),
    dsi010b1_output: Path | None = typer.Option(
        None,
        "--dsi010b1-output",
        exists=True,
        file_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/dsi010b3_residual_corporate_action_closure"),
        "--output",
    ),
) -> None:
    """Certify actual residual closures and fail closed on remaining evidence."""

    report = ResidualCorporateActionClosureEngine().run(
        baseline_b1c_output=baseline_b1c_output,
        final_b1c_output=final_b1c_output,
        baseline_htr010b_output=baseline_htr010b_output,
        final_htr010b_output=final_htr010b_output,
        official_source_root=official_source_root,
        dsi010b1_output=dsi010b1_output,
    )
    paths = ResidualCorporateActionClosureExporter().export(report, output)
    summary = report.summary
    print("DSI-010B3 Full Residual Corporate-Action Closure")
    print(f"Initial residual cases: {summary['initial_residual_count']}")
    print(f"Final residual cases: {summary['final_residual_count']}")
    print(f"Gross cases resolved: {summary['gross_resolved_count']}")
    print(f"Regressed to fail-closed: {summary['regressed_to_fail_closed_count']}")
    print(f"Net cases resolved: {summary['net_resolved_count']}")
    print(f"Resolution channels: {summary['resolution_channel_counts']}")
    print(f"Remaining evidence: {summary['remaining_reason_counts']}")
    print(f"Readiness: {summary['readiness']}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    print(
        "ADJUSTED_REPLAY_READY=" + str(bool(summary["adjusted_replay_ready"])).lower()
    )
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["residual_corporate_action_closure_certify"]
