from __future__ import annotations

from datetime import date

import pytest

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
)
from alpha.historical_truth.bridge_aware_admission_quarantine import (
    augment_quarantine_with_admission_intervals,
)
from alpha.historical_truth.bridge_aware_admission_reconciliation import (
    bridge_aware_readiness,
    overlay_bridge_aware_results,
    segmented_admission_with_bridge_reconciliation,
)


def _base(event_id: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "identity_key": "nse:isin:INE000000001",
        "symbol": "ALPHA",
        "effective_date": "2026-01-03",
        "factor_state": "FACTOR_CERTIFIED",
        "validation_outcome": "IMPLEMENTATION_DEFECT",
        "requires_quarantine": True,
        "admitted_to_replay": False,
    }


def _repair(
    event_id: str,
    *,
    proposed: str,
    factor_confirmed: bool,
    bridge_certified: bool,
    dependency: str,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "proposed_validation_outcome": proposed,
        "factor_quality_confirmed": factor_confirmed,
        "bridge_certified_for_replay": bridge_certified,
        "bridge_dependency_state": dependency,
        "corrected_disposition": "TEST_DISPOSITION",
        "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
    }


def test_overlay_separates_factor_quality_from_bridge_certification() -> None:
    base = (_base("stable"), _base("bridge"), _base("insufficient"))
    repairs = (
        _repair(
            "stable",
            proposed="FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            factor_confirmed=True,
            bridge_certified=True,
            dependency="NONE_STABLE_SECURITY",
        ),
        _repair(
            "bridge",
            proposed="FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            factor_confirmed=True,
            bridge_certified=False,
            dependency="UNCERTIFIED_CROSS_ISIN",
        ),
        _repair(
            "insufficient",
            proposed="FACTOR_INSUFFICIENT_EVIDENCE",
            factor_confirmed=False,
            bridge_certified=True,
            dependency="NONE_STABLE_SECURITY",
        ),
    )

    rows, summary = overlay_bridge_aware_results(base, repairs)
    by_event = {row["event_id"]: row for row in rows}

    assert by_event["stable"]["admitted_to_replay"] is True
    assert by_event["stable"]["requires_quarantine"] is False
    assert by_event["bridge"]["factor_quality_confirmed"] is True
    assert by_event["bridge"]["admitted_to_replay"] is False
    assert by_event["bridge"]["requires_quarantine"] is True
    assert by_event["insufficient"]["requires_quarantine"] is True
    assert summary["corrected_case_count"] == 3
    assert summary["factor_quality_confirmed_count"] == 2
    assert summary["bridge_uncertified_count"] == 1
    assert summary["implementation_defect_count"] == 0


def test_overlay_requires_exact_event_lineage() -> None:
    with pytest.raises(ValueError, match="missing from B1C"):
        overlay_bridge_aware_results(
            (_base("known"),),
            (
                _repair(
                    "missing",
                    proposed="FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
                    factor_confirmed=True,
                    bridge_certified=False,
                    dependency="UNCERTIFIED_CROSS_ISIN",
                ),
            ),
        )


def test_bridge_uncertified_and_stable_confirmed_intervals_diverge() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    coverage = (
        {
            "identity_key": "nse:isin:INE000000001",
            "symbol": "BRIDGE",
            "isin": "INE000000001",
        },
        {
            "identity_key": "nse:isin:INE000000002",
            "symbol": "STABLE",
            "isin": "INE000000002",
        },
    )
    factors = (
        {
            "factor_id": "factor-bridge",
            "canonical_event_id": "event-bridge",
            "identity_key": "nse:isin:INE000000001",
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_CERTIFIED",
        },
        {
            "factor_id": "factor-stable",
            "canonical_event_id": "event-stable",
            "identity_key": "nse:isin:INE000000002",
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_CERTIFIED",
        },
    )
    results = (
        {
            "event_id": "event-bridge",
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
            "bridge_certified_for_replay": False,
            "factor_quality_confirmed": True,
        },
        {
            "event_id": "event-stable",
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            "bridge_dependency_state": "NONE_STABLE_SECURITY",
            "bridge_certified_for_replay": True,
            "factor_quality_confirmed": True,
        },
    )

    intervals = segmented_admission_with_bridge_reconciliation(
        coverage=coverage,
        factors=factors,
        validation_results=results,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )
    pre_event = {
        row["identity_key"]: row
        for row in intervals
        if row["start_date"] == "2026-01-01"
    }

    assert pre_event["nse:isin:INE000000001"]["admission_state"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
    )
    assert pre_event["nse:isin:INE000000001"]["admitted_price_view"] == "NONE"
    assert pre_event["nse:isin:INE000000002"]["admission_state"] == (
        AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value
    )
    assert pre_event["nse:isin:INE000000002"]["admitted_price_view"] == "ADJUSTED"


def test_readiness_replaces_false_factor_blockers_with_bridge_blockers() -> None:
    results = (
        {
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
        },
        {
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_SERIES",
        },
        {
            "validation_outcome": "FACTOR_INSUFFICIENT_EVIDENCE",
            "bridge_dependency_state": "NONE_STABLE_SECURITY",
        },
    )
    intervals = (
        {"admission_state": AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value},
    )
    readiness = bridge_aware_readiness(
        base={
            "state": "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION",
            "blockers": [
                "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS",
                "POSSIBLE_FACTOR_ORIENTATION_DEFECTS",
            ],
        },
        results=results,
        intervals=intervals,
        repair_summary={
            "corrected_case_count": 3,
            "factor_quality_confirmed_count": 2,
            "bridge_uncertified_count": 2,
        },
    )

    assert readiness["implementation_defect_count"] == 0
    assert "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS" not in readiness["blockers"]
    assert "POSSIBLE_FACTOR_ORIENTATION_DEFECTS" not in readiness["blockers"]
    assert "UNCERTIFIED_CROSS_ISIN_BRIDGES" in readiness["blockers"]
    assert "UNCERTIFIED_CROSS_SERIES_BRIDGES" in readiness["blockers"]
    assert "FACTOR_INSUFFICIENT_EVIDENCE_REMAINS" in readiness["blockers"]


def test_admission_interval_quarantine_is_economically_measurable() -> None:
    evidence = (
        {
            "quarantine_id": "evidence",
            "identity_key": "nse:isin:INE000000001",
            "interval_start": "2026-01-03",
            "interval_end": "2026-01-03",
            "quarantine_reason": "UNCERTIFIED_CROSS_ISIN_BRIDGE",
        },
    )
    intervals = (
        {
            "identity_key": "nse:isin:INE000000001",
            "symbol": "ALPHA",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "admission_state": AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value,
        },
        {
            "identity_key": "nse:isin:INE000000001",
            "symbol": "ALPHA",
            "start_date": "2026-01-03",
            "end_date": "2026-01-05",
            "admission_state": (
                AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT.value
            ),
        },
    )

    rows = augment_quarantine_with_admission_intervals(evidence, intervals)

    assert len(rows) == 2
    interval_row = next(
        row for row in rows if row.get("source") == "REPLAY_ADMISSION_INTERVAL"
    )
    assert interval_row["interval_start"] == "2026-01-01"
    assert interval_row["interval_end"] == "2026-01-02"
    assert interval_row["quarantine_reason"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
    )


def test_command_registration_is_idempotent() -> None:
    first = _historical_truth_app()
    second = _historical_truth_app()
    command_name = "bridge-aware-admission-reconcile"

    assert (
        sum(command.name == command_name for command in first.registered_commands) == 1
    )
    assert (
        sum(command.name == command_name for command in second.registered_commands) == 1
    )
