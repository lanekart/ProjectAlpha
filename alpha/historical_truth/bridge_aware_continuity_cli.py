"""CLI for DSI-010B2 bridge-aware continuity certification."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.bridge_aware_continuity_artifacts import (
    BridgeAwareContinuityArtifactExporter,
    BridgeAwareContinuityCertificationEngine,
)


def bridge_aware_continuity_certify(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    htr009a2_output: Path = typer.Option(
        ...,
        "--htr009a2-output",
        exists=True,
        file_okay=False,
    ),
    htr010a3_output: Path = typer.Option(
        ...,
        "--htr010a3-output",
        exists=True,
        file_okay=False,
    ),
    htr010b_output: Path = typer.Option(
        ...,
        "--htr010b-output",
        exists=True,
        file_okay=False,
    ),
    htr010b1c_output: Path = typer.Option(
        ...,
        "--htr010b1c-output",
        exists=True,
        file_okay=False,
    ),
    htr010b1e2_output: Path = typer.Option(
        ...,
        "--htr010b1e2-output",
        exists=True,
        file_okay=False,
    ),
    dsi010b1_output: Path = typer.Option(
        ...,
        "--dsi010b1-output",
        exists=True,
        file_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/dsi010b2_bridge_aware_continuity"),
        "--output",
    ),
) -> None:
    """Certify the signed 18-event bridge-aware candle context."""

    report = BridgeAwareContinuityCertificationEngine().run(
        database_path=database,
        htr009a2_output=htr009a2_output,
        htr010a3_output=htr010a3_output,
        htr010b_output=htr010b_output,
        htr010b1c_output=htr010b1c_output,
        htr010b1e2_output=htr010b1e2_output,
        dsi010b1_output=dsi010b1_output,
    )
    paths = BridgeAwareContinuityArtifactExporter().export(report, output)
    summary = report.summary
    print("DSI-010B2 Governed Bridge-Aware Continuity Certification")
    print(
        "M/K/D/U/C: "
        f"{summary['M_complete_governed_context']}/"
        f"{summary['K_confirmed_correct']}/"
        f"{summary['D_implementation_defect']}/"
        f"{summary['U_insufficient_evidence']}/"
        f"{summary['C_conflicting_official_evidence']}"
    )
    print(f"Bridge blocker: {summary['bridge_certified_continuity_blocker_state']}")
    print(f"Global readiness: {summary['global_readiness_state']}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    print(
        "ADJUSTED_REPLAY_READY=" + str(bool(summary["adjusted_replay_ready"])).lower()
    )
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["bridge_aware_continuity_certify"]
