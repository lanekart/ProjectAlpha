from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_package import (
    HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION,
    OfficialBridgeEvidencePackageEngine,
)


def _dossiers(path: Path) -> Path:
    rows = []
    for index in range(20):
        rows.append(
            {
                "dossier_id": f"dossier-{index}",
                "bridge_type": "CROSS_SERIES" if index == 19 else "CROSS_ISIN",
                "effective_date": f"2026-01-{index + 1:02d}",
                "pre_isin": f"INE000000{index:03d}",
                "post_isin": (
                    f"INE000000{index:03d}" if index == 19 else f"INE100000{index:03d}"
                ),
                "pre_symbol": f"SYM{index}",
                "post_symbol": f"SYM{index}",
                "pre_series": "EQ",
                "post_series": "BE" if index == 19 else "EQ",
            }
        )
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _catalog(path: Path, *, missing_pre: bool = False) -> Path:
    rows = []
    for index in range(20):
        rows.append(
            {
                "symbol": f"SYM{index}",
                "effective_date": f"2026-01-{index + 1:02d}",
                "pre_isin": f"INE000000{index:03d}",
                "post_isin": (
                    f"INE000000{index:03d}" if index == 19 else f"INE100000{index:03d}"
                ),
                "pre_identity_url": (
                    None
                    if missing_pre and index == 0
                    else f"https://nsearchives.nseindia.com/pre-{index}.html"
                ),
                "action_url": (
                    "https://www.nseindia.com/companies-listing/"
                    f"corporate-filings-actions?symbol=SYM{index}"
                ),
                "post_identity_url": (
                    f"https://nsearchives.nseindia.com/post-{index}.html"
                ),
            }
        )
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_build_findings_creates_complete_three_role_packages(tmp_path: Path) -> None:
    report = OfficialBridgeEvidencePackageEngine().build_findings(
        dossiers_path=_dossiers(tmp_path / "dossiers.json"),
        source_catalog_path=_catalog(tmp_path / "catalog.json"),
    )

    assert report["contract_version"] == HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION
    assert report["generated_document_request_count"] == 60
    assert report["complete_source_package_count"] == 20
    assert report["incomplete_source_package_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert {row["evidence_role"] for row in report["findings"]} == {
        "PRE_IDENTITY",
        "CORPORATE_ACTION",
        "POST_IDENTITY",
    }


def test_missing_pre_source_remains_explicitly_incomplete(tmp_path: Path) -> None:
    report = OfficialBridgeEvidencePackageEngine().build_findings(
        dossiers_path=_dossiers(tmp_path / "dossiers.json"),
        source_catalog_path=_catalog(tmp_path / "catalog.json", missing_pre=True),
    )

    assert report["generated_document_request_count"] == 59
    assert report["complete_source_package_count"] == 19
    assert report["incomplete_source_package_count"] == 1
    incomplete = next(
        row
        for row in report["packages"]
        if row["package_state"] != "READY_FOR_GOVERNED_DOWNLOAD"
    )
    assert incomplete["missing_roles"] == ["PRE_IDENTITY"]


def _review_inputs(
    tmp_path: Path, *, action_has_date: bool = True
) -> tuple[Path, Path, Path]:
    dossiers_path = _dossiers(tmp_path / "dossiers.json")
    root = tmp_path / "raw"
    discoveries = []
    for index in range(20):
        effective_date = f"2026-01-{index + 1:02d}"
        pre_isin = f"INE000000{index:03d}"
        post_isin = pre_isin if index == 19 else f"INE100000{index:03d}"
        for role, text in (
            ("PRE_IDENTITY", f"SYM{index} ISIN {pre_isin}"),
            (
                "CORPORATE_ACTION",
                (
                    f"SYM{index} stock split effective {effective_date}"
                    if action_has_date or index != 0
                    else f"SYM{index} stock split"
                ),
            ),
            ("POST_IDENTITY", f"SYM{index} ISIN {post_isin}"),
        ):
            relative_path = f"dossier-{index}/{role}.html"
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            discoveries.append(
                {
                    "dossier_id": f"dossier-{index}",
                    "document_id": f"doc-{index}-{role}",
                    "source_url": f"https://nsearchives.nseindia.com/{index}-{role}.html",
                    "source_class": (
                        "NSE_CORPORATE_ACTION_NOTICE"
                        if role == "CORPORATE_ACTION"
                        else "NSE_SECURITY_MASTER"
                    ),
                    "evidence_role": role,
                    "effective_date": effective_date,
                    "document_date": effective_date,
                    "relative_path": relative_path,
                    "source_sha256": "a" * 64,
                    "download_state": "DOWNLOADED_VERIFIED_BYTES",
                    "production_influence": False,
                }
            )
    discoveries_path = tmp_path / "discoveries.json"
    discoveries_path.write_text(json.dumps(discoveries), encoding="utf-8")
    return dossiers_path, discoveries_path, root


def test_semantic_review_certifies_only_complete_downloaded_packages(
    tmp_path: Path,
) -> None:
    dossiers, discoveries, root = _review_inputs(tmp_path)
    report = OfficialBridgeEvidencePackageEngine().review_downloaded_packages(
        dossiers_path=dossiers,
        acquisition_discoveries_path=discoveries,
        downloaded_documents_root=root,
    )

    assert report["semantically_verified_package_count"] == 20
    assert report["insufficient_semantic_package_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert all(
        row["identity_continuity_certified"] is True
        for row in report["reviewed_discoveries"]
    )
    assert all(
        row["price_series_continuity_certified"] is False
        for row in report["reviewed_discoveries"]
    )


def test_semantic_review_fails_closed_when_action_date_is_missing(
    tmp_path: Path,
) -> None:
    dossiers, discoveries, root = _review_inputs(tmp_path, action_has_date=False)
    report = OfficialBridgeEvidencePackageEngine().review_downloaded_packages(
        dossiers_path=dossiers,
        acquisition_discoveries_path=discoveries,
        downloaded_documents_root=root,
    )

    assert report["semantically_verified_package_count"] == 19
    assert report["insufficient_semantic_package_count"] == 1
    failed = next(
        row
        for row in report["package_results"]
        if row["semantic_package_state"] == "INSUFFICIENT_SEMANTIC_PACKAGE_EVIDENCE"
    )
    assert failed["corporate_action_proved"] is False
    assert all(
        row["identity_continuity_certified"] is None
        for row in report["reviewed_discoveries"]
        if row["dossier_id"] == failed["dossier_id"]
    )
