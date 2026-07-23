"""CLI for governed HTR-010B1F discovery population."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.official_bridge_evidence_population import (
    OfficialBridgeEvidenceDiscoveryPopulationEngine,
)


def official_bridge_evidence_populate(
    discovery_registry: Path = typer.Option(
        ...,
        "--discovery-registry",
        exists=True,
        dir_okay=False,
    ),
    reviewed_findings: Path | None = typer.Option(
        None,
        "--reviewed-findings",
        exists=True,
        dir_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_evidence_population_2026"),
        "--output",
    ),
) -> None:
    """Merge reviewed official-source findings into governed discovery rows."""

    engine = OfficialBridgeEvidenceDiscoveryPopulationEngine()
    report = engine.run(
        discovery_registry_path=discovery_registry,
        reviewed_findings_path=reviewed_findings,
    )
    paths = engine.export(report, output)
    print("HTR-010B1F Official Bridge Evidence Discovery Population")
    print(f"Contract: {report['contract_version']}")
    print(f"Registry rows: {report['input_registry_count']:,}")
    print(f"Reviewed findings: {report['input_reviewed_finding_count']:,}")
    print(f"Populated sources: {report['populated_official_source_count']:,}")
    print(f"Pending sources: {report['pending_official_source_count']:,}")
    print(f"Rejected findings: {report['rejected_finding_count']:,}")
    print(f"Implementation defects: {report['implementation_defect_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Evidence downloads: 0")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")
    if report["implementation_defect_count"]:
        raise typer.Exit(code=1)


__all__ = ["official_bridge_evidence_populate"]
