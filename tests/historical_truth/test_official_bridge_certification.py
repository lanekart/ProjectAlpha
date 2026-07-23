from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.historical_truth.official_bridge_certification import (
    BridgeCertificationDecision,
    OfficialBridgeCertificationEngine,
)


def _write_cases(root: Path, cases: list[dict[str, object]]) -> None:
    root.mkdir(parents=True)
    (root / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps(cases), encoding="utf-8"
    )


def _case(
    *,
    case_id: str,
    bridge_type: str,
    prior_isin: str,
    current_isin: str,
    prior_series: str = "EQ",
    current_series: str = "EQ",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
        "effective_date": "2026-02-01",
        "bridge_type": bridge_type,
        "bridge_dependency_state": (
            "UNCERTIFIED_CROSS_ISIN"
            if bridge_type == "CROSS_ISIN"
            else "UNCERTIFIED_CROSS_SERIES"
        ),
        "prior_isin": prior_isin,
        "current_isin": current_isin,
        "prior_symbol": "ALPHA",
        "current_symbol": "ALPHA",
        "prior_series": prior_series,
        "current_series": current_series,
        "factor_quality_confirmed": True,
    }


def _population() -> list[dict[str, object]]:
    cases = [
        _case(
            case_id=f"isin-{index}",
            bridge_type="CROSS_ISIN",
            prior_isin=f"INE000000{index:03d}",
            current_isin=f"INE100000{index:03d}",
        )
        for index in range(23)
    ]
    cases.append(
        _case(
            case_id="kotyark-series",
            bridge_type="CROSS_SERIES",
            prior_isin="INE0J0B01017",
            current_isin="INE0J0B01017",
            prior_series="EQ",
            current_series="BE",
        )
    )
    return cases


def _official_evidence(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": "evidence-1",
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
    }
    row.update(overrides)
    return row


def test_missing_official_evidence_fails_closed_for_all_cases(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, _population())

    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=None,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    assert report["input_bridge_case_count"] == 24
    assert report["cross_isin_case_count"] == 23
    assert report["cross_series_case_count"] == 1
    assert report["insufficient_official_evidence_count"] == 24
    assert report["unclassified_bridge_case_count"] == 0
    assert report["silent_identity_assumption_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False


def test_official_effective_dated_lineage_certifies_identity(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, _population())
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps([_official_evidence()]), encoding="utf-8")

    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=evidence,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    certified = next(row for row in report["cases"] if row["bridge_case_id"] == "isin-0")
    assert certified["continuity_decision"] == (
        BridgeCertificationDecision.CERTIFIED_CONTINUOUS_IDENTITY.value
    )
    assert certified["adjusted_replay_certified"] is True
    assert report["certified_continuous_identity_count"] == 1


def test_unofficial_or_unhashed_evidence_cannot_certify(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, _population())
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps([_official_evidence(source_class="PRICE_SIMILARITY", source_sha256="")]),
        encoding="utf-8",
    )

    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=evidence,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    row = next(item for item in report["cases"] if item["bridge_case_id"] == "isin-0")
    assert row["continuity_decision"] == (
        BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value
    )
    assert row["adjusted_replay_certified"] is False


def test_conflicting_official_evidence_remains_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, _population())
    evidence = tmp_path / "evidence.json"
    positive = _official_evidence(evidence_id="positive")
    negative = _official_evidence(
        evidence_id="negative", identity_continuity_certified=False
    )
    evidence.write_text(json.dumps([positive, negative]), encoding="utf-8")

    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=evidence,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    row = next(item for item in report["cases"] if item["bridge_case_id"] == "isin-0")
    assert row["continuity_decision"] == (
        BridgeCertificationDecision.CONFLICTING_OFFICIAL_EVIDENCE.value
    )
    assert row["adjusted_replay_certified"] is False


def test_cross_series_requires_tradability_continuity(tmp_path: Path) -> None:
    source = tmp_path / "d2"
    _write_cases(source, _population())
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            [
                _official_evidence(
                    evidence_id="kotyark",
                    source_class="NSE_SECURITY_MASTER",
                    pre_isin="INE0J0B01017",
                    post_isin="INE0J0B01017",
                    pre_series="EQ",
                    post_series="BE",
                    tradability_continuity_certified=False,
                )
            ]
        ),
        encoding="utf-8",
    )

    report = OfficialBridgeCertificationEngine().run(
        htr010b1d2_output=source,
        official_evidence_path=evidence,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    row = next(
        item for item in report["cases"] if item["bridge_case_id"] == "kotyark-series"
    )
    assert row["identity_continuity_certified"] is True
    assert row["tradability_continuity_certified"] is False
    assert row["adjusted_replay_certified"] is False
