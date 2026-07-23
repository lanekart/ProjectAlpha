"""CLI for HTR-010B1F official bridge evidence and certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.official_bridge_certification import (
    OfficialBridgeCertificationEngine,
)
from alpha.historical_truth.official_bridge_evidence_dossier import (
    OfficialBridgeEvidenceDossierBuilder,
)
from alpha.historical_truth.official_bridge_evidence_manifest import (
    OfficialBridgeEvidenceManifestBuilder,
)


def official_bridge_evidence_manifest(
    htr010b1d2_output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair_2026"),
        "--htr010b1d2-output",
        exists=True,
        file_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_evidence_manifest_2026"),
        "--output",
    ),
) -> None:
    """Build the deterministic 24-case official-evidence acquisition manifest."""

    report = OfficialBridgeEvidenceManifestBuilder().run(
        htr010b1d2_output=htr010b1d2_output
    )
    paths = OfficialBridgeEvidenceManifestBuilder.export(report, output)
    print("HTR-010B1F Official Bridge Evidence Manifest")
    print(f"Contract: {report['contract_version']}")
    print(f"Bridge cases: {report['input_bridge_case_count']:,}")
    print(f"Cross-ISIN cases: {report['cross_isin_case_count']:,}")
    print(f"Cross-series cases: {report['cross_series_case_count']:,}")
    print(f"Implementation defects: {report['implementation_defect_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Evidence downloads: 0")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")
    if report["implementation_defect_count"]:
        raise typer.Exit(code=1)


def official_bridge_evidence_dossiers(
    evidence_manifest_output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_evidence_manifest_2026"),
        "--evidence-manifest-output",
        exists=True,
        file_okay=False,
    ),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_evidence_dossiers_2026"),
        "--output",
    ),
) -> None:
    """Collapse 24 immutable cases into unique official-document dossiers."""

    report = OfficialBridgeEvidenceDossierBuilder().run(
        evidence_manifest_output=evidence_manifest_output
    )
    paths = OfficialBridgeEvidenceDossierBuilder.export(report, output)
    print("HTR-010B1F Official Bridge Evidence Dossiers")
    print(f"Contract: {report['contract_version']}")
    print(f"Input bridge cases: {report['input_bridge_case_count']:,}")
    print(f"Unique dossiers: {report['unique_dossier_count']:,}")
    print(f"Multi-case dossiers: {report['multi_case_dossier_count']:,}")
    print(f"Maximum cases per dossier: {report['maximum_cases_per_dossier']:,}")
    print(f"Implementation defects: {report['implementation_defect_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Evidence downloads: 0")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")
    if report["implementation_defect_count"]:
        raise typer.Exit(code=1)


def official_bridge_certify(
    htr010b1d2_output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair_2026"),
        "--htr010b1d2-output",
        exists=True,
        file_okay=False,
    ),
    official_evidence: Path | None = typer.Option(
        None,
        "--official-evidence",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_certification_2026"),
        "--output",
    ),
) -> None:
    """Certify or explicitly fail-close all official identity bridge cases."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=htr010b1d2_output,
        official_evidence_path=official_evidence,
        start_date=start_date,
        end_date=end_date,
    )
    paths = OfficialBridgeCertificationEngine.export(report, output)
    print("HTR-010B1F Official Identity and Series Bridge Certification")
    print(f"Contract: {report['contract_version']}")
    print(f"Bridge cases: {report['input_bridge_case_count']:,}")
    print(f"Cross-ISIN cases: {report['cross_isin_case_count']:,}")
    print(f"Cross-series cases: {report['cross_series_case_count']:,}")
    print(f"Certified continuous: {report['certified_continuous_identity_count']:,}")
    print(
        "Certified noncontinuous: "
        f"{report['certified_noncontinuous_identity_count']:,}"
    )
    print(
        "Insufficient official evidence: "
        f"{report['insufficient_official_evidence_count']:,}"
    )
    print(
        "Conflicting official evidence: "
        f"{report['conflicting_official_evidence_count']:,}"
    )
    print(f"Unclassified bridge cases: {report['unclassified_bridge_case_count']:,}")
    print(f"Implementation defects: {report['implementation_defect_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")
    if report["implementation_defect_count"]:
        raise typer.Exit(code=1)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = [
    "official_bridge_certify",
    "official_bridge_evidence_dossiers",
    "official_bridge_evidence_manifest",
]
