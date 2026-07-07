from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from alpha.backtest import (
    BacktestExportArtifact,
    BacktestExportManifest,
    BacktestExportSession,
)


def test_backtest_export_artifact_is_immutable_and_serializable() -> None:
    artifact = BacktestExportArtifact(kind=" JSON ", path=Path("report.json"))

    assert artifact.kind == "json"
    assert artifact.as_dict() == {
        "kind": "json",
        "path": "report.json",
    }

    with pytest.raises(FrozenInstanceError):
        artifact.kind = "text"  # type: ignore[misc]


def test_backtest_export_artifact_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="artifact kind cannot be empty"):
        BacktestExportArtifact(kind=" ", path=Path("report.json"))


def test_backtest_export_manifest_orders_artifacts_deterministically() -> None:
    manifest = BacktestExportManifest(
        (
            BacktestExportArtifact(kind="text", path=Path("z.txt")),
            BacktestExportArtifact(kind="json", path=Path("b.json")),
            BacktestExportArtifact(kind="json", path=Path("a.json")),
        )
    )

    assert manifest.as_dict() == {
        "artifact_count": 3,
        "artifacts": [
            {"kind": "json", "path": "a.json"},
            {"kind": "json", "path": "b.json"},
            {"kind": "text", "path": "z.txt"},
        ],
    }


def test_backtest_export_manifest_exposes_empty_state() -> None:
    manifest = BacktestExportManifest(())

    assert manifest.artifact_count == 0
    assert manifest.is_empty is True
    assert manifest.as_dict() == {
        "artifact_count": 0,
        "artifacts": [],
    }


def test_backtest_export_manifest_includes_session_when_present() -> None:
    session = BacktestExportSession(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
    )
    manifest = BacktestExportManifest(
        (BacktestExportArtifact(kind="json", path=Path("report.json")),),
        session=session,
    )

    assert manifest.as_dict() == {
        "artifact_count": 1,
        "artifacts": [
            {"kind": "json", "path": "report.json"},
        ],
        "session": session.as_dict(),
    }


def test_backtest_export_manifest_exports_json() -> None:
    manifest = BacktestExportManifest(
        (BacktestExportArtifact(kind="json", path=Path("report.json")),)
    )

    assert json.loads(manifest.as_json()) == manifest.as_dict()
    assert manifest.as_json() == json.dumps(
        manifest.as_dict(),
        sort_keys=True,
    )
    assert "\n" in manifest.as_json(indent=2)
