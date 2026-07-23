"""CLI for the end-to-end HTR-010B1F completion bundle."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.official_bridge_completion import (
    OfficialBridgeCompletionEngine,
)


def official_bridge_complete(
    htr010b1d2_output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair_2026"),
        "--htr010b1d2-output",
        exists=True,
        file_okay=False,
    ),
    reviewed_findings: Path | None = typer.Option(
        None,
        "--reviewed-findings",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    download_documents: bool = typer.Option(
        False,
        "--download-documents/--no-download-documents",
    ),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_completion_2026"),
        "--output",
    ),
) -> None:
    """Run the complete governed B1F evidence and certification workflow."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")

    report = OfficialBridgeCompletionEngine().run(
        htr010b1d2_output=htr010b1d2_output,
        reviewed_findings_path=reviewed_findings,
        output=output,
        start_date=start_date,
        end_date=end_date,
        download_documents=download_documents,
    )
    print("HTR-010B1F Completion Bundle")
    print(f"Contract: {report['contract_version']}")
    print(f"Bridge cases: {report['input_bridge_case_count']:,}")
    print(f"Unique dossiers: {report['unique_dossier_count']:,}")
    print(f"Populated official sources: {report['populated_official_source_count']:,}")
    print(f"Pending official sources: {report['pending_official_source_count']:,}")
    print(f"Downloaded documents: {report['downloaded_document_count']:,}")
    print(
        f"Verified official documents: {report['verified_official_document_count']:,}"
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
    print(f"Replay readiness: {report['replay_readiness']}")
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


__all__ = ["official_bridge_complete"]
