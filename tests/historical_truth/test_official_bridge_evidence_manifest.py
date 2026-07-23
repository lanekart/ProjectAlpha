from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_manifest import (
    HTR010B1F_EVIDENCE_MANIFEST_VERSION,
    OfficialBridgeEvidenceManifestBuilder,
)


def _case(index: int, *, bridge_type: str = "CROSS_ISIN") -> dict[str, object]:
    cross_isin = bridge_type == "CROSS_ISIN"
    return {
        "case_id": f"case-{index}",
        "effective_date": "2026-02-01",
        "bridge_type": bridge_type,
        "bridge_dependency_state": (
            "UNCERTIFIED_CROSS_ISIN"
            if cross_isin
            else "UNCERTIFIED_CROSS_SERIES"
        ),
        "prior_isin": f"INE000000{index:03d}",
        "current_isin": (
            f"INE100000{index:03d}" if cross_isin else f"INE000000{index:03d}"
        ),
        "prior_symbol": "KOTYARK" if not cross_isin else f"OLD{index}",
        "current_symbol": "KOTYARK" if not cross_isin else f"NEW{index}",
        "prior_series": "EQ",
        "current_series": "BE" if not cross_isin else "EQ",
    }


def _write_cases(root: Path, cases: list[dict[str, object]]) -> None:
    root.mkdir(parents=True)
    (root / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps(cases), encoding="utf-8"
    )


def test_manifest_builds_exact_governed_24_case_population(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    cases = [_case(index) for index in range(23)]
    cases.append(_case(23, bridge_type="CROSS_SERIES"))
    _write_cases(source, cases)

    report = OfficialBridgeEvidenceManifestBuilder().run(
        htr010b1d2_output=source
    )

    assert report["contract_version"] == HTR010B1F_EVIDENCE_MANIFEST_VERSION
    assert report["input_bridge_case_count"] == 24
    assert report["cross_isin_case_count"] == 23
    assert report["cross_series_case_count"] == 1
    assert report["implementation_defect_count"] == 0
    assert report["evidence_download_performed"] is False
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False


def test_cross_series_manifest_requests_tradability_evidence(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    cases = [_case(index) for index in range(23)]
    cases.append(_case(23, bridge_type="CROSS_SERIES"))
    _write_cases(source, cases)

    report = OfficialBridgeEvidenceManifestBuilder().run(
        htr010b1d2_output=source
    )
    request = next(
        row for row in report["requests"] if row["bridge_type"] == "CROSS_SERIES"
    )

    assert request["pre_series"] == "EQ"
    assert request["post_series"] == "BE"
    assert any(
        "tradability continuity" in question.lower()
        for question in request["required_official_questions"]
    )
    assert request["evidence_status"] == "PENDING_OFFICIAL_EVIDENCE"


def test_manifest_export_produces_blank_evidence_template(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    cases = [_case(index) for index in range(23)]
    cases.append(_case(23, bridge_type="CROSS_SERIES"))
    _write_cases(source, cases)
    report = OfficialBridgeEvidenceManifestBuilder().run(
        htr010b1d2_output=source
    )

    output = tmp_path / "out"
    paths = OfficialBridgeEvidenceManifestBuilder.export(report, output)
    template = json.loads(
        (output / "htr010b1f_official_evidence_template.json").read_text()
    )

    assert len(paths) == 5
    assert len(template) == 24
    assert all(row["document_id"] is None for row in template)
    assert all(row["identity_continuity_certified"] is None for row in template)
    assert all(row["production_influence"] is False for row in template)


def test_manifest_reports_population_contract_defect(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, [_case(1)])

    report = OfficialBridgeEvidenceManifestBuilder().run(
        htr010b1d2_output=source
    )

    assert report["implementation_defect_count"] > 0
    assert "EXPECTED_24_BRIDGE_CASES_FOUND_1" in report["implementation_defects"]
