from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_package import (
    OfficialBridgeEvidencePackageEngine,
)


def test_json_action_evidence_closes_complete_semantic_package(tmp_path: Path) -> None:
    dossier_id = "htr010b1f-dossier:test"
    dossiers = [
        {
            "dossier_id": dossier_id,
            "effective_date": "2026-01-14",
            "pre_isin": "INE298G01027",
            "post_isin": "INE298G01035",
            "pre_symbol": "AJMERA",
            "post_symbol": "AJMERA",
            "pre_series": "EQ",
            "post_series": "EQ",
        }
    ]
    dossiers_path = tmp_path / "dossiers.json"
    dossiers_path.write_text(json.dumps(dossiers), encoding="utf-8")

    raw = tmp_path / "raw"
    raw.mkdir()
    pre_path = raw / "pre.html"
    action_path = raw / "action.json"
    post_path = raw / "post.csv"
    pre_path.write_text("AJMERA INE298G01027", encoding="utf-8")
    action_path.write_text(
        json.dumps(
            [
                {
                    "symbol": "AJMERA",
                    "exDate": "14-Jan-2026",
                    "purpose": "Face Value Split (Sub-Division)",
                }
            ]
        ),
        encoding="utf-8",
    )
    post_path.write_text("AJMERA,EQ,INE298G01035", encoding="utf-8")

    discoveries = [
        _discovery(dossier_id, "PRE_IDENTITY", pre_path.name),
        _discovery(dossier_id, "CORPORATE_ACTION", action_path.name),
        _discovery(dossier_id, "POST_IDENTITY", post_path.name),
    ]
    discoveries_path = tmp_path / "discoveries.json"
    discoveries_path.write_text(json.dumps(discoveries), encoding="utf-8")

    report = OfficialBridgeEvidencePackageEngine().review_downloaded_packages(
        dossiers_path=dossiers_path,
        acquisition_discoveries_path=discoveries_path,
        downloaded_documents_root=raw,
    )

    result = report["package_results"][0]
    assert result["identity_continuity_certified"] is True
    assert result["corporate_action_state"] == "ACTION_ROW_VERIFIED"
    assert result["unresolved_reasons"] == []
    assert report["pre_identity_proved_count"] == 1
    assert report["corporate_action_proved_count"] == 1
    assert report["post_identity_proved_count"] == 1


def test_mcx_remains_explicitly_unresolved_without_pre_identity(tmp_path: Path) -> None:
    dossier_id = "htr010b1f-dossier:mcx"
    dossiers = [
        {
            "dossier_id": dossier_id,
            "effective_date": "2026-01-02",
            "pre_isin": "INE745G01035",
            "post_isin": "INE745G01043",
            "pre_symbol": "MCX",
            "post_symbol": "MCX",
            "pre_series": "EQ",
            "post_series": "EQ",
        }
    ]
    dossiers_path = tmp_path / "dossiers.json"
    dossiers_path.write_text(json.dumps(dossiers), encoding="utf-8")

    raw = tmp_path / "raw"
    raw.mkdir()
    action_path = raw / "action.json"
    post_path = raw / "post.csv"
    action_path.write_text(
        json.dumps(
            [
                {
                    "symbol": "MCX",
                    "exDate": "02-Jan-2026",
                    "purpose": "Face Value Split",
                }
            ]
        ),
        encoding="utf-8",
    )
    post_path.write_text("MCX,EQ,INE745G01043", encoding="utf-8")

    discoveries = [
        _discovery(dossier_id, "CORPORATE_ACTION", action_path.name),
        _discovery(dossier_id, "POST_IDENTITY", post_path.name),
    ]
    discoveries_path = tmp_path / "discoveries.json"
    discoveries_path.write_text(json.dumps(discoveries), encoding="utf-8")

    report = OfficialBridgeEvidencePackageEngine().review_downloaded_packages(
        dossiers_path=dossiers_path,
        acquisition_discoveries_path=discoveries_path,
        downloaded_documents_root=raw,
    )

    result = report["package_results"][0]
    assert result["corporate_action_proved"] is True
    assert result["post_identity_proved"] is True
    assert result["pre_identity_proved"] is False
    assert result["identity_continuity_certified"] is False
    assert "PRE_IDENTITY_DOCUMENT_UNAVAILABLE" in result["unresolved_reasons"]


def _discovery(dossier_id: str, role: str, relative_path: str) -> dict[str, object]:
    return {
        "dossier_id": dossier_id,
        "document_id": f"{dossier_id}:{role}",
        "evidence_role": role,
        "relative_path": relative_path,
        "download_state": "DOWNLOADED_VERIFIED_BYTES",
        "production_influence": False,
    }
