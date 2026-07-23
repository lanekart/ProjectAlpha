from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_document_downloader import (
    OfficialBridgeDocumentDownloader,
)
from alpha.historical_truth.official_bridge_source_role_validation import (
    validate_source_role_url,
)


def test_generic_dynamic_action_table_is_rejected() -> None:
    valid, reason = validate_source_role_url(
        "CORPORATE_ACTION",
        "https://www.nseindia.com/companies-listing/"
        "corporate-filings-actions?symbol=AJMERA&tabIndex=equity",
    )

    assert valid is False
    assert reason == "GENERIC_DYNAMIC_ACTION_TABLE_NOT_ROLE_EVIDENCE"


def test_server_rendered_quote_page_is_allowed_for_action_and_post_identity() -> None:
    url = "https://www.nseindia.com/get-quote/equity/AJMERA"

    assert validate_source_role_url("CORPORATE_ACTION", url)[0] is True
    assert validate_source_role_url("POST_IDENTITY", url)[0] is True


def test_static_xbrl_is_allowed_for_identity_roles() -> None:
    url = (
        "https://nsearchives.nseindia.com/corporate/ixbrl/"
        "INTEGRATED_FILING_INDAS_105340_24072025185511_iXBRL_WEB.html"
    )

    assert validate_source_role_url("PRE_IDENTITY", url)[0] is True
    assert validate_source_role_url("POST_IDENTITY", url)[0] is True


def test_downloader_rejects_wrong_role_before_network(tmp_path: Path) -> None:
    discoveries = tmp_path / "discoveries.json"
    discoveries.write_text(
        json.dumps(
            [
                {
                    "dossier_id": "dossier-1",
                    "evidence_role": "CORPORATE_ACTION",
                    "source_url": (
                        "https://www.nseindia.com/companies-listing/"
                        "corporate-filings-actions?symbol=AJMERA&tabIndex=equity"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )

    report = OfficialBridgeDocumentDownloader().run(
        discoveries_path=discoveries,
        output_root=tmp_path / "raw",
    )

    assert report["downloaded_document_count"] == 0
    assert report["rejected_role_source_count"] == 1
    assert report["downloads"][0]["download_state"] == ("REJECTED_ROLE_SOURCE_MISMATCH")
    assert report["downloads"][0]["error"] == (
        "GENERIC_DYNAMIC_ACTION_TABLE_NOT_ROLE_EVIDENCE"
    )


def test_catalog_uses_role_appropriate_action_sources() -> None:
    catalog_path = Path(
        "alpha/historical_truth/official_bridge_evidence_source_catalog.json"
    )
    rows = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert len(rows) == 20
    assert sum(row["pre_identity_url"] is None for row in rows) == 1
    for row in rows:
        action_valid, action_reason = validate_source_role_url(
            "CORPORATE_ACTION",
            row["action_url"],
        )
        post_valid, post_reason = validate_source_role_url(
            "POST_IDENTITY",
            row["post_identity_url"],
        )
        assert action_valid, (row["symbol"], action_reason)
        assert post_valid, (row["symbol"], post_reason)
