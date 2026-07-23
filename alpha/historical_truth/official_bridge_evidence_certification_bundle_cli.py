"""CLI for the HTR-010B1F official evidence certification bundle."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.official_bridge_evidence_certification_bundle import (
    OfficialBridgeEvidenceCertificationBundle,
)

_DEFAULT_CATALOG = Path(__file__).with_name("official_bridge_evidence_source_catalog.json")


def official_bridge_evidence_certify_all(
    htr010b1d2_output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair_2026"),
        "--htr010b1d2-output",
        exists=True,
        file_okay=False,
    ),
    source_catalog: Path = typer.Option(
        _DEFAULT_CATALOG,
        "--source-catalog",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_evidence_certification_bundle_2026"),
        "--output",
    ),
) -> None:
    """Acquire, semantically verify and certify all 20 bridge dossiers."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")

    report = OfficialBridgeEvidenceCertificationBundle().run(
        htr010b1d2_output=htr010b1d2_output,
        source_catalog_path=source_catalog,
        output=output,
        start_date=start_date,
        end_date=end_date,
    )
    print("HTR-010B1F Official Evidence Certification Bundle")
    print(f"Contract: {report['contract_version']}")
    print(f"Bridge cases: {report['input_bridge_case_count']:,}")
    print(f"Unique dossiers: {report['unique_dossier_count']:,}")
    print(f"Complete source packages: {report['complete_source_package_count']:,}")
    print(f"Incomplete source packages: {report['incomplete_source_package_count']:,}")
    print(f"Requested documents: {report['requested_document_count']:,}")
    print(f"Downloaded documents: {report['downloaded_document_count']:,}")
    print(f"Failed downloads: {report['failed_download_count']:,}")
    print(
        "Semantically verified packages: "
        f"{report['semantically_verified_package_count']:,}"
    )
    print(
        "Insufficient semantic packages: "
        f"{report['insufficient_semantic_package_count']:,}"
    )
    print(
        "Verified official documents: "
        f"{report['verified_official_document_count']:,}"
    )
    print(f"Covered bridge cases: {report['covered_bridge_case_count']:,}")
    print(
        "Certified continuous identities: "
        f"{report['certified_continuous_identity_count']:,}"
    )
    print(
        "Insufficient official evidence: "
        f"{report['insufficient_official_evidence_count']:,}"
    )
    print(f"Implementation defects: {report['implementation_defect_count']:,}")
    print(f"Milestone status: {report['milestone_status']}")
    print(f"Readiness blockers: {report['readiness_blockers']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")
    if report["implementation_defect_count"]:
        raise typer.Exit(code=1)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["official_bridge_evidence_certify_all"]
