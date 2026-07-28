"""CLI for DSI-010B4 final pre-2016 adjusted-history closure."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.final_pre2016_adjusted_history_closure import (
    FinalPre2016AdjustedHistoryClosureEngine,
    FinalPre2016AdjustedHistoryClosureExporter,
)


def final_pre2016_adjusted_history_closure_certify(
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
    dsi010b1_output: Path | None = typer.Option(
        None, "--dsi010b1-output", exists=True, file_okay=False
    ),
    output: Path = typer.Option(
        Path("artifacts/dsi010b4_final_pre2016_adjusted_history_closure"),
        "--output",
    ),
) -> None:
    """Certify actual B4 closure and preserve every remaining blocker."""

    report = FinalPre2016AdjustedHistoryClosureEngine().run(
        baseline_b1c_output=baseline_b1c_output,
        final_b1c_output=final_b1c_output,
        baseline_htr010b_output=baseline_htr010b_output,
        final_htr010b_output=final_htr010b_output,
        dsi010b1_output=dsi010b1_output,
    )
    paths = FinalPre2016AdjustedHistoryClosureExporter().export(report, output)
    summary = report.summary
    print("DSI-010B4 Final Pre-2016 Corporate-Action Closure")
    print(f"Starting residual cases: {summary['starting_case_count']}")
    print(f"Resolved cases: {summary['resolved_case_count']}")
    print(f"Remaining cases: {summary['remaining_case_count']}")
    print(f"Resolution channels: {summary['resolution_channel_counts']}")
    print(f"Validation outcomes: {summary['validation_outcome_counts']}")
    print(
        "Mixed price-basis intervals: "
        f"{summary['mixed_price_basis_intervals_before']} -> "
        f"{summary['mixed_price_basis_intervals_after']}"
    )
    print(f"Readiness: {summary['readiness']}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    print(
        "ADJUSTED_REPLAY_READY=" + str(bool(summary["adjusted_replay_ready"])).lower()
    )
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["final_pre2016_adjusted_history_closure_certify"]
