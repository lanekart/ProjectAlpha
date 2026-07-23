"""CLI for governed HTR-010B1F official document downloads."""

from __future__ import annotations

from pathlib import Path

import typer

from alpha.historical_truth.official_bridge_document_downloader import (
    OfficialBridgeDocumentDownloader,
)


def official_bridge_document_download(
    discoveries: Path = typer.Option(
        ...,
        "--discoveries",
        exists=True,
        dir_okay=False,
    ),
    documents_root: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_documents_2026"),
        "--documents-root",
    ),
    output: Path = typer.Option(
        Path("artifacts/htr010b1f_official_bridge_download_2026"),
        "--output",
    ),
) -> None:
    """Download only allowlisted official-source bridge documents."""

    engine = OfficialBridgeDocumentDownloader()
    report = engine.run(
        discoveries_path=discoveries,
        output_root=documents_root,
    )
    paths = engine.export(report, output)
    print("HTR-010B1F Official Bridge Document Download")
    print(f"Contract: {report['contract_version']}")
    print(f"Input discoveries: {report['input_discovery_count']:,}")
    print(f"Downloaded documents: {report['downloaded_document_count']:,}")
    print(f"Rejected sources: {report['rejected_source_count']:,}")
    print(f"Failed downloads: {report['failed_download_count']:,}")
    print(f"Pending URLs: {report['pending_url_count']:,}")
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["official_bridge_document_download"]
