"""CLI for DSI-010B1 legacy rights reference bridge certification."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.legacy_rights_reference_bridge_artifacts import (
    LegacyRightsBridgeArtifactExporter,
    LegacyRightsBridgeCertificationEngine,
)


def legacy_rights_reference_bridge_certify(
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
    htr010b1e2_output: Path = typer.Option(
        ...,
        "--htr010b1e2-output",
        exists=True,
        file_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/dsi010b1_legacy_rights_reference_bridge"),
        "--output",
    ),
) -> None:
    """Certify the fixed 39-case legacy missing-ISIN bridge population."""

    report = LegacyRightsBridgeCertificationEngine().run(
        htr009a2_output=htr009a2_output,
        htr010a3_output=htr010a3_output,
        htr010b_output=htr010b_output,
        htr010b1e2_output=htr010b1e2_output,
    )
    paths = LegacyRightsBridgeArtifactExporter().export(report, output)
    print("DSI-010B1 Governed Legacy ISIN Bridge Certification")
    print(f"Bridge cases: {report.summary['bridge_case_count']}")
    print(f"Eligible bridges: {report.summary['eligible_bridge_count']}")
    print(
        f"Rights-reference blocker: {report.summary['rights_reference_blocker_state']}"
    )
    print(f"Readiness: {report.summary['readiness_state']}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["legacy_rights_reference_bridge_certify"]
