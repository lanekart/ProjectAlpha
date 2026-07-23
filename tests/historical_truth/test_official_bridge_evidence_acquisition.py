from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_acquisition import (
    OfficialBridgeEvidenceAcquisitionEngine,
)


def _dossiers(path: Path) -> None:
    rows = [
        {
            "dossier_id": f"dossier-{index}",
            "bridge_case_ids": [f"case-{index}"],
            "production_influence": False,
        }
        for index in range(20)
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def _discovery(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": "evidence-1",
        "dossier_id": "dossier-0",
        "bridge_case_id": "case-0",
        "source_class": "NSE_CORPORATE_ACTION_NOTICE",
        "source_url": "https://nsearchives.nseindia.com/document.pdf",
        "document_id": "NSE/2026/001",
        "document_date": "2026-01-01",
        "effective_date": "2026-01-02",
        "relative_path": "nse/document.pdf",
        "pre_isin": "INE000000001",
        "post_isin": "INE000000002",
        "identity_continuity_certified": True,
        "price_series_continuity_certified": True,
        "tradability_continuity_certified": True,
        "production_influence": False,
    }
    row.update(overrides)
    return row


def test_missing_download_remains_fail_closed(tmp_path: Path) -> None:
    dossiers = tmp_path / "dossiers.json"
    discoveries = tmp_path / "discoveries.json"
    _dossiers(dossiers)
    discoveries.write_text(json.dumps([_discovery()]), encoding="utf-8")

    report = OfficialBridgeEvidenceAcquisitionEngine().run(
        dossiers_path=dossiers,
        discoveries_path=discoveries,
        downloaded_documents_root=tmp_path / "downloads",
    )

    assert report["input_dossier_count"] == 20
    assert report["missing_document_count"] == 1
    assert report["verified_official_document_count"] == 0
    assert report["implementation_defect_count"] == 0


def test_downloaded_bytes_are_hashed_and_admitted(tmp_path: Path) -> None:
    dossiers = tmp_path / "dossiers.json"
    discoveries = tmp_path / "discoveries.json"
    downloads = tmp_path / "downloads"
    document = downloads / "nse" / "document.pdf"
    document.parent.mkdir(parents=True)
    payload = b"official exchange document"
    document.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    _dossiers(dossiers)
    discoveries.write_text(
        json.dumps([_discovery(source_sha256=digest)]), encoding="utf-8"
    )

    report = OfficialBridgeEvidenceAcquisitionEngine().run(
        dossiers_path=dossiers,
        discoveries_path=discoveries,
        downloaded_documents_root=downloads,
    )

    assert report["verified_official_document_count"] == 1
    assert report["hash_mismatch_count"] == 0
    row = report["documents"][0]
    assert row["actual_sha256"] == digest
    assert row["acquisition_state"] == "VERIFIED_OFFICIAL_DOCUMENT"


def test_hash_mismatch_is_not_admissible(tmp_path: Path) -> None:
    dossiers = tmp_path / "dossiers.json"
    discoveries = tmp_path / "discoveries.json"
    downloads = tmp_path / "downloads"
    document = downloads / "nse" / "document.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"official exchange document")
    _dossiers(dossiers)
    discoveries.write_text(
        json.dumps([_discovery(source_sha256="a" * 64)]), encoding="utf-8"
    )

    report = OfficialBridgeEvidenceAcquisitionEngine().run(
        dossiers_path=dossiers,
        discoveries_path=discoveries,
        downloaded_documents_root=downloads,
    )

    assert report["hash_mismatch_count"] == 1
    assert report["verified_official_document_count"] == 0


def test_unofficial_discovery_is_rejected(tmp_path: Path) -> None:
    dossiers = tmp_path / "dossiers.json"
    discoveries = tmp_path / "discoveries.json"
    _dossiers(dossiers)
    discoveries.write_text(
        json.dumps([_discovery(source_class="PRICE_SIMILARITY")]),
        encoding="utf-8",
    )

    report = OfficialBridgeEvidenceAcquisitionEngine().run(
        dossiers_path=dossiers,
        discoveries_path=discoveries,
        downloaded_documents_root=None,
    )

    assert report["invalid_discovery_count"] == 1
    assert report["verified_official_document_count"] == 0


def test_export_separates_only_verified_evidence(tmp_path: Path) -> None:
    dossiers = tmp_path / "dossiers.json"
    discoveries = tmp_path / "discoveries.json"
    downloads = tmp_path / "downloads"
    document = downloads / "nse" / "document.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"official exchange document")
    _dossiers(dossiers)
    discoveries.write_text(json.dumps([_discovery()]), encoding="utf-8")
    engine = OfficialBridgeEvidenceAcquisitionEngine()
    report = engine.run(
        dossiers_path=dossiers,
        discoveries_path=discoveries,
        downloaded_documents_root=downloads,
    )
    output = tmp_path / "output"

    paths = engine.export(report, output)

    admissible = json.loads(
        (output / "htr010b1f_admissible_official_evidence.json").read_text()
    )
    assert len(paths) == 5
    assert len(admissible) == 1
    assert admissible[0]["source_sha256"] == sha256(
        b"official exchange document"
    ).hexdigest()
