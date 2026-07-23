from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.__main__ import _historical_truth_app


def _discoveries(path: Path) -> Path:
    rows = [
        {
            "dossier_id": "dossier-1",
            "source_url": None,
            "production_influence": False,
        }
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_downloader_command_is_registered() -> None:
    commands = {command.name for command in _historical_truth_app().registered_commands}

    assert "official-bridge-document-download" in commands


def test_pending_url_download_run_is_deterministic(tmp_path: Path) -> None:
    discoveries = _discoveries(tmp_path / "discoveries.json")
    documents = tmp_path / "documents"
    output = tmp_path / "output"

    result = CliRunner().invoke(
        _historical_truth_app(),
        [
            "official-bridge-document-download",
            "--discoveries",
            str(discoveries),
            "--documents-root",
            str(documents),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Downloaded documents: 0" in result.output
    assert "Pending URLs: 1" in result.output
    assert "Full benchmark replays: 0" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    report_path = output / "htr010b1f_download_report.json"
    registry_path = output / "htr010b1f_download_registry.json"
    assert report_path.exists()
    assert registry_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["pending_url_count"] == 1
    assert report["downloaded_document_count"] == 0
    assert report["production_influence"] is False
