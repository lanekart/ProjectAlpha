from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.legacy_rights_reference_bridge_artifacts import (
    LegacyRightsBridgeArtifactExporter,
    LegacyRightsBridgeCertificationEngine,
)
from tests.historical_truth.legacy_bridge_test_support import (
    fixture_source_contract,
    write_bridge_fixture,
)


def test_complete_bridge_population_is_certified_and_deterministic(
    tmp_path: Path,
) -> None:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path / "source")
    htr010b, htr010b1e2 = _downstream_fixture(tmp_path)
    engine = LegacyRightsBridgeCertificationEngine()
    contract = fixture_source_contract(htr009a2)

    report = engine.run(
        htr009a2_output=htr009a2,
        htr010a3_output=htr010a3,
        htr010b_output=htr010b,
        htr010b1e2_output=htr010b1e2,
        source_contract=contract,
    )

    assert report.summary["bridge_case_count"] == 39
    assert report.summary["eligible_bridge_count"] == 2
    assert report.summary["rights_reference_blocker_state"] == "PARTIALLY_REDUCED"
    assert report.summary["rebuilt_rights_factor_states"] == {
        "FACTOR_CERTIFIED_REFERENCE_PRICE": 39,
        "FACTOR_PROVISIONAL_REFERENCE_PRICE": 38,
        "FACTOR_UNKNOWN_MISSING_TERMS": 28,
    }
    assert report.summary["certificate_eligible"] is True
    assert report.summary["state_checks"]["certified_bridge_provenance_is_complete"]
    assert report.summary["state_checks"][
        "certified_bridge_factors_enter_cumulative_factors"
    ]
    assert report.summary["state_checks"][
        "rejected_bridges_do_not_enter_cumulative_factors"
    ]
    assert report.summary["state_checks"]["rejected_bridges_do_not_enter_replay"]
    assert report.summary["state_checks"][
        "mismatch_does_not_enter_cumulative_or_replay"
    ]
    assert len(report.certificate_sha256) == 64
    assert len(report.certificate["bridge_cases_sha256"]) == 64
    assert len(report.certificate["rejections_sha256"]) == 64
    assert len(report.certificate["summary_sha256"]) == 64
    assert len(report.certificate["report_markdown_sha256"]) == 64
    assert any(
        row["symbol"] == "TATAPOWER"
        and row["rejection_reason"] == "PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE"
        for row in report.rejections
    )
    first = LegacyRightsBridgeArtifactExporter().export(
        report,
        tmp_path / "output-a",
    )
    second = LegacyRightsBridgeArtifactExporter().export(
        report,
        tmp_path / "output-b",
    )
    assert [path.name for path in first] == [path.name for path in second]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]


def _downstream_fixture(root: Path) -> tuple[Path, Path]:
    htr010b = root / "htr010b"
    htr010b1e2 = root / "htr010b1e2"
    htr010b.mkdir()
    htr010b1e2.mkdir()
    events = []
    factors = []
    cumulative = []
    validations = []

    for index in range(39):
        event_id = f"event-missing-{index:02d}"
        factor_id = f"factor-missing-{index:02d}"
        certified = index < 2
        events.append(_event(event_id, f"SYMBOL{index:02d}", "INE000A01010"))
        factors.append(
            {
                **_factor(event_id, factor_id),
                "factor_state": (
                    "FACTOR_CERTIFIED_REFERENCE_PRICE"
                    if certified
                    else "FACTOR_PROVISIONAL_REFERENCE_PRICE"
                ),
                "reference_price_original_provenance_state": "PRIOR_ISIN_MISSING",
                "reference_price_provenance_state": (
                    "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE_PRIOR_CLOSE"
                    if certified
                    else "PRIOR_ISIN_MISSING"
                ),
                "reference_price_bridge_state": (
                    "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
                    if certified
                    else "NO_MATCHING_OFFICIAL_INTERVAL"
                ),
                "reference_price_bridge_rejection_reason": (
                    None if certified else "NO_MATCHING_OFFICIAL_INTERVAL"
                ),
            }
        )
        if certified:
            cumulative.append({"factor_ids": [factor_id]})
        validations.append(
            {
                "event_id": event_id,
                "validation_outcome": (
                    "FACTOR_INSUFFICIENT_EVIDENCE"
                    if certified
                    else "FACTOR_REQUIRES_REFERENCE_PRICE"
                ),
                "admitted_to_replay": False,
            }
        )

    events.append(_event("event-tatapower", "TATAPOWER", "INE245A01021"))
    factors.append(
        {
            **_factor("event-tatapower", "factor-tatapower"),
            "identity_key": "nse:isin:INE245A01021",
            "factor_state": "FACTOR_PROVISIONAL_REFERENCE_PRICE",
            "reference_price_original_provenance_state": "PRIOR_ISIN_MISMATCH",
            "reference_price_provenance_state": "PRIOR_ISIN_MISMATCH",
            "reference_price_isin": "INE245A01013",
            "reference_price_bridge_state": "NOT_APPLICABLE",
        }
    )
    validations.append(
        {
            "event_id": "event-tatapower",
            "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
            "admitted_to_replay": False,
        }
    )

    for index in range(37):
        event_id = f"event-strict-{index:02d}"
        events.append(_event(event_id, f"STRICT{index:02d}", "INE000A01010"))
        factors.append(
            {
                **_factor(event_id, f"factor-strict-{index:02d}"),
                "factor_state": "FACTOR_CERTIFIED_REFERENCE_PRICE",
                "reference_price_original_provenance_state": (
                    "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"
                ),
                "reference_price_provenance_state": (
                    "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"
                ),
                "reference_price_isin": "INE000A01010",
                "reference_price_bridge_state": "NOT_APPLICABLE",
            }
        )
    for index in range(28):
        event_id = f"event-missing-terms-{index:02d}"
        events.append(_event(event_id, f"TERMS{index:02d}", "INE000A01010"))
        factors.append(
            {
                **_factor(event_id, f"factor-terms-{index:02d}"),
                "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
                "reference_price_original_provenance_state": "PRIOR_CANDLE_MISSING",
                "reference_price_provenance_state": "PRIOR_CANDLE_MISSING",
                "reference_price_bridge_state": "NOT_APPLICABLE",
            }
        )

    _write(htr010b / "htr010b_canonical_events.json", events)
    _write(htr010b / "htr010b_adjustment_factors.json", factors)
    _write(htr010b / "htr010b_cumulative_factors.json", cumulative)
    _write(
        htr010b / "htr010b_executive_report.json",
        {
            "contract_version": "HTR-010B-v1.1.0",
            "report_sha256": "e" * 64,
            "production_influence": False,
        },
    )
    _write(
        htr010b1e2 / "htr010b1_factor_validation_results.json",
        validations,
    )
    _write(
        htr010b1e2 / "htr010b1_replay_readiness.json",
        {
            "state": "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION",
            "blockers": ["FACTOR_INSUFFICIENT_EVIDENCE_REMAINS"],
            "final_unresolved_interval_count": 0,
            "production_influence": False,
        },
    )
    return htr010b, htr010b1e2


def _event(event_id: str, symbol: str, isin: str) -> dict[str, object]:
    return {
        "canonical_event_id": event_id,
        "action_type": "RIGHTS",
        "symbol": symbol,
        "isin": isin,
        "effective_date": "2015-01-05",
    }


def _factor(event_id: str, factor_id: str) -> dict[str, object]:
    return {
        "canonical_event_id": event_id,
        "factor_id": factor_id,
        "identity_key": "nse:isin:INE000A01010",
        "reference_price_series": "EQ",
        "reference_price_date": "2015-01-02",
        "reference_price_isin": None,
        "reference_price": 100.0,
        "reference_price_source_sha256": "f" * 64,
        "reference_price_bridge_contract_version": (
            "HTR-010B1-LEGACY-ISIN-REFERENCE-BRIDGE-v1.0.0"
        ),
        "reference_price_bridge_identity": "nse:isin:INE000A01010",
        "reference_price_bridge_membership_interval_ids": ["membership-1"],
        "reference_price_bridge_membership_states": [
            "UNRESOLVED_NO_TERMINATION_EVIDENCE"
        ],
        "reference_price_bridge_membership_confidence": "HIGH",
        "reference_price_bridge_membership_event_ids": ["event-source"],
        "reference_price_bridge_symbol_interval_ids": ["symbol-1"],
        "reference_price_bridge_symbol_confidence": "HIGH",
        "reference_price_bridge_symbol_event_ids": ["event-source"],
        "reference_price_bridge_tradability_interval_ids": ["tradability-1"],
        "reference_price_bridge_official_event_ids": ["event-source"],
        "reference_price_bridge_official_source_ids": ["nse-source"],
        "reference_price_bridge_evidence_sha256": {"nse-source": "a" * 64},
        "reference_price_bridge_overlapping_identities": [],
        "reference_price_bridge_symbol_reuse_conflict": False,
        "reference_price_bridge_symbol_change_conflict": False,
        "reference_price_bridge_series_transition_conflict": False,
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
