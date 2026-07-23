from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.historical_truth.official_bridge_completion import (
    HTR010B1F_COMPLETION_CONTRACT_VERSION,
    OfficialBridgeCompletionEngine,
    _merge_downloads_into_discoveries,
)


def _case(index: int) -> dict[str, object]:
    if index == 23:
        return {
            "case_id": "kotyark-series",
            "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
            "effective_date": "2026-06-24",
            "bridge_type": "CROSS_SERIES",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_SERIES",
            "prior_isin": "INE0J0B01017",
            "current_isin": "INE0J0B01017",
            "prior_symbol": "KOTYARK",
            "current_symbol": "KOTYARK",
            "prior_series": "EQ",
            "current_series": "BE",
            "factor_quality_confirmed": True,
        }

    if index >= 15:
        duplicate_index = (index - 15) // 2
        return {
            "case_id": f"duplicate-{duplicate_index}-{index % 2}",
            "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
            "effective_date": f"2026-02-{duplicate_index + 1:02d}",
            "bridge_type": "CROSS_ISIN",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
            "prior_isin": f"INE200000{duplicate_index:03d}",
            "current_isin": f"INE300000{duplicate_index:03d}",
            "prior_symbol": f"DUP{duplicate_index}",
            "current_symbol": f"DUP{duplicate_index}",
            "prior_series": "EQ",
            "current_series": "EQ",
            "factor_quality_confirmed": True,
        }

    return {
        "case_id": f"cross-isin-{index}",
        "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
        "effective_date": f"2026-01-{index + 1:02d}",
        "bridge_type": "CROSS_ISIN",
        "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
        "prior_isin": f"INE000000{index:03d}",
        "current_isin": f"INE100000{index:03d}",
        "prior_symbol": f"SYM{index}",
        "current_symbol": f"SYM{index}",
        "prior_series": "EQ",
        "current_series": "EQ",
        "factor_quality_confirmed": True,
    }


def _upstream(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps([_case(index) for index in range(24)]),
        encoding="utf-8",
    )
    return root


def test_completion_bundle_runs_all_stages_fail_closed(tmp_path: Path) -> None:
    report = OfficialBridgeCompletionEngine().run(
        htr010b1d2_output=_upstream(tmp_path / "upstream"),
        reviewed_findings_path=None,
        output=tmp_path / "completion",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
        download_documents=False,
    )

    assert report["contract_version"] == HTR010B1F_COMPLETION_CONTRACT_VERSION
    assert report["input_bridge_case_count"] == 24
    assert report["unique_dossier_count"] == 20
    assert report["pending_official_source_count"] == 20
    assert report["downloaded_document_count"] == 0
    assert report["verified_official_document_count"] == 0
    assert report["covered_bridge_case_count"] == 0
    assert report["insufficient_official_evidence_count"] == 24
    assert report["implementation_defect_count"] == 0
    assert report["replay_readiness"] == (
        "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    )
    assert report["readiness_blockers"] == [
        "INSUFFICIENT_OFFICIAL_BRIDGE_EVIDENCE",
        "INCOMPLETE_CASE_LEVEL_EVIDENCE_COVERAGE",
    ]
    assert report["benchmark_replay_count"] == 0
    assert report["adjusted_replay_integration_enabled"] is False
    assert report["production_influence"] is False
    assert (tmp_path / "completion" / "htr010b1f_completion_report.json").exists()
    assert (tmp_path / "completion" / "08_certification").is_dir()


def test_download_metadata_merges_back_into_governed_discovery() -> None:
    discoveries = [
        {
            "dossier_id": "dossier-1",
            "source_url": "https://nseindia.com/source.pdf",
            "document_id": "NSE/1",
            "effective_date": "2026-01-01",
        }
    ]
    downloads = [
        {
            "dossier_id": "dossier-1",
            "source_url": "https://nseindia.com/source.pdf",
            "final_url": "https://nsearchives.nseindia.com/source.pdf",
            "relative_path": "dossier-1/hash.pdf",
            "source_sha256": "a" * 64,
            "download_state": "DOWNLOADED_VERIFIED_BYTES",
            "error": None,
        }
    ]

    rows = _merge_downloads_into_discoveries(discoveries, downloads)

    assert rows[0]["document_id"] == "NSE/1"
    assert rows[0]["source_url"] == (
        "https://nsearchives.nseindia.com/source.pdf"
    )
    assert rows[0]["relative_path"] == "dossier-1/hash.pdf"
    assert rows[0]["source_sha256"] == "a" * 64
    assert rows[0]["production_influence"] is False


def test_completion_report_is_deterministic(tmp_path: Path) -> None:
    upstream = _upstream(tmp_path / "upstream")
    engine = OfficialBridgeCompletionEngine()
    first = engine.run(
        htr010b1d2_output=upstream,
        reviewed_findings_path=None,
        output=tmp_path / "first",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
        download_documents=False,
    )
    second = engine.run(
        htr010b1d2_output=upstream,
        reviewed_findings_path=None,
        output=tmp_path / "second",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
        download_documents=False,
    )

    assert first["report_sha256"] == second["report_sha256"]
