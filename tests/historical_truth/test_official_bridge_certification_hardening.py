from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.historical_truth.official_bridge_certification import (
    BridgeCertificationDecision,
    OfficialBridgeCertificationEngine,
)


def _write_case(root: Path, *, factor_quality_confirmed: bool = True) -> None:
    root.mkdir(parents=True)
    cases = []
    for index in range(23):
        cases.append(
            {
                "case_id": f"isin-{index}",
                "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
                "effective_date": "2026-02-01",
                "bridge_type": "CROSS_ISIN",
                "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
                "prior_isin": f"INE000000{index:03d}",
                "current_isin": f"INE100000{index:03d}",
                "prior_symbol": f"OLD{index}",
                "current_symbol": f"NEW{index}",
                "prior_series": "EQ",
                "current_series": "EQ",
                "factor_quality_confirmed": factor_quality_confirmed,
            }
        )
    cases.append(
        {
            "case_id": "kotyark-series",
            "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
            "effective_date": "2026-02-01",
            "bridge_type": "CROSS_SERIES",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_SERIES",
            "prior_isin": "INE0J0B01017",
            "current_isin": "INE0J0B01017",
            "prior_symbol": "KOTYARK",
            "current_symbol": "KOTYARK",
            "prior_series": "EQ",
            "current_series": "BE",
            "factor_quality_confirmed": factor_quality_confirmed,
        }
    )
    (root / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps(cases), encoding="utf-8"
    )


def _evidence(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": "official-1",
        "bridge_case_id": "isin-0",
        "source_class": "NSE_SYMBOL_CHANGE_NOTICE",
        "document_id": "NSE/2026/001",
        "document_date": "2026-01-30",
        "effective_date": "2026-02-01",
        "source_sha256": "a" * 64,
        "pre_isin": "INE000000000",
        "post_isin": "INE100000000",
        "identity_continuity_certified": True,
        "price_series_continuity_certified": True,
        "tradability_continuity_certified": True,
        "production_influence": False,
    }
    row.update(overrides)
    return row


def _run(source: Path, evidence: Path | None) -> dict[str, object]:
    return OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=evidence,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )


def test_invalid_sha256_is_not_official_evidence(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_case(source)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps([_evidence(source_sha256="not-a-sha")]), encoding="utf-8"
    )

    report = _run(source, evidence)
    row = next(item for item in report["cases"] if item["bridge_case_id"] == "isin-0")

    assert row["continuity_decision"] == (
        BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value
    )
    assert row["adjusted_replay_certified"] is False


def test_bridge_case_id_mismatch_cannot_cross_certify(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_case(source)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps([_evidence(bridge_case_id="isin-1")]), encoding="utf-8"
    )

    report = _run(source, evidence)
    row = next(item for item in report["cases"] if item["bridge_case_id"] == "isin-0")

    assert row["continuity_decision"] == (
        BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value
    )


def test_factor_quality_must_be_confirmed_for_adjusted_replay(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_case(source, factor_quality_confirmed=False)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps([_evidence()]), encoding="utf-8")

    report = _run(source, evidence)
    row = next(item for item in report["cases"] if item["bridge_case_id"] == "isin-0")

    assert row["identity_continuity_certified"] is True
    assert row["price_series_continuity_certified"] is True
    assert row["factor_basis_compatible"] is False
    assert row["adjusted_replay_certified"] is False


def test_export_separates_unresolved_evidence_cases(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_case(source)
    report = _run(source, None)
    output = tmp_path / "out"

    paths = OfficialBridgeCertificationEngine.export(report, output)
    unresolved = json.loads(
        (output / "htr010b1f_unresolved_official_evidence.json").read_text()
    )

    assert len(paths) == 5
    assert len(unresolved) == 24
    assert all(
        row["continuity_decision"]
        == BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value
        for row in unresolved
    )
