from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_materialization import (
    OfficialBridgeEvidenceMaterializationEngine,
)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _dossiers() -> list[dict[str, object]]:
    rows = [
        {
            "dossier_id": f"dossier-{index}",
            "bridge_case_ids": [f"case-{index}"],
            "effective_date": f"2026-01-{index + 1:02d}",
            "pre_isin": f"INE000000{index:03d}",
            "post_isin": f"INE100000{index:03d}",
            "pre_symbol": f"SYM{index}",
            "post_symbol": f"SYM{index}",
            "pre_series": "EQ",
            "post_series": "EQ",
        }
        for index in range(19)
    ]
    rows.append(
        {
            "dossier_id": "dossier-duplicate",
            "bridge_case_ids": ["duplicate-a", "duplicate-b"],
            "effective_date": "2026-04-02",
            "pre_isin": "INE012Q01021",
            "post_isin": "INE012Q01039",
            "pre_symbol": "RNBDENIMS",
            "post_symbol": "RNBDENIMS",
            "pre_series": "BE",
            "post_series": "BE",
        }
    )
    return rows


def _document(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dossier_id": "dossier-duplicate",
        "source_class": "NSE_CORPORATE_ACTION_NOTICE",
        "document_id": "NSE/2026/001",
        "document_date": "2026-03-20",
        "effective_date": "2026-04-02",
        "source_url": "https://nse.example/document.pdf",
        "source_sha256": "a" * 64,
        "pre_isin": "INE012Q01021",
        "post_isin": "INE012Q01039",
        "pre_series": "BE",
        "post_series": "BE",
        "identity_continuity_certified": True,
        "price_series_continuity_certified": True,
        "tradability_continuity_certified": True,
        "production_influence": False,
    }
    row.update(overrides)
    return row


def test_shared_dossier_document_materializes_to_each_case(tmp_path: Path) -> None:
    dossiers_path = tmp_path / "dossiers.json"
    documents_path = tmp_path / "documents.json"
    _write(dossiers_path, _dossiers())
    _write(documents_path, [_document()])

    report = OfficialBridgeEvidenceMaterializationEngine().run(
        dossiers_path=dossiers_path,
        admissible_documents_path=documents_path,
    )

    assert report["input_dossier_count"] == 20
    assert report["input_verified_document_count"] == 1
    assert report["materialized_case_evidence_count"] == 2
    assert report["covered_bridge_case_count"] == 2
    assert report["rejected_document_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert {row["bridge_case_id"] for row in report["case_evidence"]} == {
        "duplicate-a",
        "duplicate-b",
    }
    assert all(
        row["independent_certification_decision_required"] is True
        for row in report["case_evidence"]
    )


def test_unknown_dossier_document_is_rejected(tmp_path: Path) -> None:
    dossiers_path = tmp_path / "dossiers.json"
    documents_path = tmp_path / "documents.json"
    _write(dossiers_path, _dossiers())
    _write(documents_path, [_document(dossier_id="missing")])

    report = OfficialBridgeEvidenceMaterializationEngine().run(
        dossiers_path=dossiers_path,
        admissible_documents_path=documents_path,
    )

    assert report["materialized_case_evidence_count"] == 0
    assert report["rejected_document_count"] == 1
    assert report["rejected_documents"][0]["materialization_state"] == (
        "UNKNOWN_DOSSIER"
    )


def test_document_dossier_mismatch_is_fail_closed(tmp_path: Path) -> None:
    dossiers_path = tmp_path / "dossiers.json"
    documents_path = tmp_path / "documents.json"
    _write(dossiers_path, _dossiers())
    _write(documents_path, [_document(post_isin="INE999999999")])

    report = OfficialBridgeEvidenceMaterializationEngine().run(
        dossiers_path=dossiers_path,
        admissible_documents_path=documents_path,
    )

    assert report["materialized_case_evidence_count"] == 0
    assert report["rejected_document_count"] == 1
    assert report["rejected_documents"][0]["materialization_state"] == (
        "DOCUMENT_DOSSIER_MISMATCH"
    )


def test_materialization_export_is_deterministic(tmp_path: Path) -> None:
    dossiers_path = tmp_path / "dossiers.json"
    documents_path = tmp_path / "documents.json"
    _write(dossiers_path, _dossiers())
    _write(documents_path, [_document()])
    engine = OfficialBridgeEvidenceMaterializationEngine()
    report = engine.run(
        dossiers_path=dossiers_path,
        admissible_documents_path=documents_path,
    )
    paths = engine.export(report, tmp_path / "output")

    assert len(paths) == 5
    assert all(path.exists() for path in paths)
    assert report["report_sha256"]
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False
