from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_document_downloader import (
    OfficialBridgeDocumentDownloader,
    _official_url,
    _suffix,
)


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_blank_url_remains_pending(tmp_path: Path) -> None:
    discoveries = tmp_path / "discoveries.json"
    _write(discoveries, [{"dossier_id": "dossier-1", "source_url": None}])

    report = OfficialBridgeDocumentDownloader().run(
        discoveries_path=discoveries,
        output_root=tmp_path / "documents",
    )

    assert report["pending_url_count"] == 1
    assert report["downloaded_document_count"] == 0
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False


def test_unofficial_host_is_rejected_without_network(tmp_path: Path) -> None:
    discoveries = tmp_path / "discoveries.json"
    _write(
        discoveries,
        [
            {
                "dossier_id": "dossier-1",
                "source_url": "https://example.com/document.pdf",
            }
        ],
    )

    report = OfficialBridgeDocumentDownloader().run(
        discoveries_path=discoveries,
        output_root=tmp_path / "documents",
    )

    assert report["rejected_source_count"] == 1
    assert report["failed_download_count"] == 0
    assert report["downloads"][0]["error"] == "SOURCE_HOST_NOT_ALLOWLISTED"


def test_official_url_allowlist_is_subdomain_safe() -> None:
    assert _official_url("https://nsearchives.nseindia.com/file.pdf") is True
    assert _official_url("https://www.bseindia.com/file.pdf") is True
    assert _official_url("https://evilnseindia.com/file.pdf") is False
    assert _official_url("http://nseindia.com/file.pdf") is False


def test_suffix_uses_content_type_before_url() -> None:
    assert _suffix("application/pdf", "https://nseindia.com/view") == ".pdf"
    assert _suffix("text/html", "https://nseindia.com/file.pdf") == ".html"
    assert _suffix(None, "https://nseindia.com/file.zip") == ".zip"


def test_export_is_deterministic(tmp_path: Path) -> None:
    discoveries = tmp_path / "discoveries.json"
    _write(discoveries, [])
    engine = OfficialBridgeDocumentDownloader()
    report = engine.run(
        discoveries_path=discoveries,
        output_root=tmp_path / "documents",
    )
    paths = engine.export(report, tmp_path / "output")

    assert len(paths) == 2
    assert all(path.exists() for path in paths)
    assert report["report_sha256"]
