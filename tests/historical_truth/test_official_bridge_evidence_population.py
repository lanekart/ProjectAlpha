from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_population import (
    OfficialBridgeEvidenceDiscoveryPopulationEngine,
)


def _registry_row(index: int) -> dict[str, object]:
    return {
        "dossier_id": f"dossier-{index}",
        "effective_date": "2026-01-02",
        "pre_isin": f"INE000000{index:03d}",
        "post_isin": f"INE100000{index:03d}",
        "pre_symbol": f"SYM{index}",
        "post_symbol": f"SYM{index}",
        "pre_series": "EQ",
        "post_series": "EQ",
        "discovery_state": "PENDING_OFFICIAL_SOURCE_DISCOVERY",
        "production_influence": False,
    }


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def _registry() -> list[dict[str, object]]:
    return [_registry_row(index) for index in range(20)]


def _finding(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dossier_id": "dossier-0",
        "source_class": "NSE_CORPORATE_ACTION_NOTICE",
        "source_url": "https://nsearchives.nseindia.com/document.pdf",
        "document_id": "NSE/2026/001",
        "document_date": "2025-12-31",
        "effective_date": "2026-01-02",
        "pre_isin": "INE000000000",
        "post_isin": "INE100000000",
        "pre_series": "EQ",
        "post_series": "EQ",
    }
    row.update(overrides)
    return row


def test_no_findings_preserve_all_pending_rows(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write(registry, _registry())

    report = OfficialBridgeEvidenceDiscoveryPopulationEngine().run(
        discovery_registry_path=registry,
        reviewed_findings_path=None,
    )

    assert report["input_registry_count"] == 20
    assert report["populated_official_source_count"] == 0
    assert report["pending_official_source_count"] == 20
    assert report["implementation_defect_count"] == 0


def test_valid_official_finding_populates_one_dossier(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    findings = tmp_path / "findings.json"
    _write(registry, _registry())
    _write(findings, [_finding()])

    report = OfficialBridgeEvidenceDiscoveryPopulationEngine().run(
        discovery_registry_path=registry,
        reviewed_findings_path=findings,
    )

    assert report["populated_official_source_count"] == 1
    assert report["pending_official_source_count"] == 19
    assert report["rejected_finding_count"] == 0


def test_nonofficial_host_is_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    findings = tmp_path / "findings.json"
    _write(registry, _registry())
    _write(findings, [_finding(source_url="https://evilnseindia.com/document.pdf")])

    report = OfficialBridgeEvidenceDiscoveryPopulationEngine().run(
        discovery_registry_path=registry,
        reviewed_findings_path=findings,
    )

    assert report["populated_official_source_count"] == 0
    assert report["rejected_finding_count"] == 1
    rejected = report["rejected_findings"][0]
    assert "SOURCE_URL_NOT_OFFICIAL_HTTPS" in rejected["validation_reasons"]


def test_cross_dossier_isin_mismatch_is_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    findings = tmp_path / "findings.json"
    _write(registry, _registry())
    _write(findings, [_finding(pre_isin="INE999999999")])

    report = OfficialBridgeEvidenceDiscoveryPopulationEngine().run(
        discovery_registry_path=registry,
        reviewed_findings_path=findings,
    )

    assert report["rejected_finding_count"] == 1
    rejected = report["rejected_findings"][0]
    assert "PRE_ISIN_MISMATCH" in rejected["validation_reasons"]


def test_unknown_dossier_is_rejected_without_polluting_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    findings = tmp_path / "findings.json"
    _write(registry, _registry())
    _write(findings, [_finding(dossier_id="unknown")])

    report = OfficialBridgeEvidenceDiscoveryPopulationEngine().run(
        discovery_registry_path=registry,
        reviewed_findings_path=findings,
    )

    assert report["pending_official_source_count"] == 20
    assert report["rejected_finding_count"] == 1
    assert report["implementation_defect_count"] == 0
