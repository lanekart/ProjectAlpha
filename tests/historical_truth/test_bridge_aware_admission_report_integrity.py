from __future__ import annotations

from alpha.historical_truth.adjustment_replay_admission_models import AdmissionState
from alpha.historical_truth.bridge_aware_admission_report_integrity import (
    _final_residual_summary,
    _synchronized_readiness,
    repair_unresolved_intervals,
)


def _interval(outcomes: list[str], dependencies: list[str]) -> dict[str, object]:
    return {
        "admission_interval_id": "old",
        "identity_key": "nse:isin:TEST",
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "admission_state": AdmissionState.UNRESOLVED.value,
        "future_bridge_validation_outcomes": outcomes,
        "future_bridge_dependencies": dependencies,
    }


def test_unresolved_reference_price_interval_becomes_factor_unknown() -> None:
    repaired, summary = repair_unresolved_intervals(
        (
            _interval(["FACTOR_REQUIRES_REFERENCE_PRICE"], []),
        )
    )

    assert repaired[0]["admission_state"] == AdmissionState.FACTOR_UNKNOWN_QUARANTINED
    assert repaired[0]["b1e1_resolution_cause"] == "FACTOR_REQUIRES_REFERENCE_PRICE"
    assert summary["post_repair_unresolved_interval_count"] == 0


def test_uncertified_bridge_takes_priority_over_confirmed_factor() -> None:
    repaired, summary = repair_unresolved_intervals(
        (
            _interval(
                ["FACTOR_CONFIRMED_CORRECT_MARKET_GAP"],
                ["UNCERTIFIED_CROSS_ISIN"],
            ),
        )
    )

    assert repaired[0]["admission_state"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED
    )
    assert repaired[0]["admitted_price_view"] == "NONE"
    assert summary["post_repair_unresolved_interval_count"] == 0


def test_confirmed_factor_without_bridge_dependency_is_adjusted() -> None:
    repaired, summary = repair_unresolved_intervals(
        (
            _interval(["FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS"], []),
        )
    )

    assert repaired[0]["admission_state"] == (
        AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL
    )
    assert repaired[0]["admitted_price_view"] == "ADJUSTED"
    assert summary["post_repair_unresolved_interval_count"] == 0


def test_final_residual_summary_uses_reconciled_rows() -> None:
    summary = _final_residual_summary(
        (
            {"residual_attribution": "BRIDGE_AWARE_FACTOR_CONFIRMED"},
            {"residual_attribution": "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED"},
            {"residual_attribution": "BRIDGE_AWARE_INSUFFICIENT_EVIDENCE"},
        )
    )

    assert summary["source"] == "FINAL_BRIDGE_AWARE_VALIDATION_RESULTS"
    assert summary["attribution_counts"] == {
        "BRIDGE_AWARE_FACTOR_CONFIRMED": 1,
        "BRIDGE_AWARE_INSUFFICIENT_EVIDENCE": 1,
        "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED": 1,
    }


def test_readiness_population_counts_and_alias_are_synchronized() -> None:
    results = (
        {
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            "bridge_certified_for_replay": False,
            "bridge_aware_reconciliation_applied": True,
        },
    )
    intervals = (
        {
            "admission_state": AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
        },
    )
    reporting = {
        "admission_quarantined_identity_count": 577,
        "evidence_quarantined_identity_count": 787,
        "unresolved_case_identity_count": 0,
    }
    residual = {"attribution_counts": {"FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED": 1}}
    interval_summary = {"post_repair_unresolved_interval_count": 0}

    readiness = _synchronized_readiness(
        {"state": "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"},
        results,
        intervals,
        reporting,
        residual,
        interval_summary,
    )

    assert readiness["admission_quarantined_identity_count"] == 577
    assert readiness["evidence_quarantined_identity_count"] == 787
    assert readiness["bridge_uncertified_count"] == 1
    assert readiness["bridge_uncertified_case_count"] == 1
    assert readiness["post_repair_unresolved_interval_count"] == 0
