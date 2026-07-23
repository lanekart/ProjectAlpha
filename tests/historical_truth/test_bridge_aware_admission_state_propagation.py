from __future__ import annotations

from datetime import date

import pytest

from alpha.historical_truth.adjustment_replay_admission_models import AdmissionState
from alpha.historical_truth.bridge_aware_admission_state_propagation import (
    propagated_admission_intervals,
)


def _coverage(identity: str) -> tuple[dict[str, object], ...]:
    return (
        {
            "identity_key": identity,
            "symbol": "ALPHA",
            "series": "EQ",
            "isin": identity.removeprefix("nse:isin:"),
        },
    )


def _factor(identity: str) -> tuple[dict[str, object], ...]:
    return (
        {
            "factor_id": "factor-1",
            "canonical_event_id": "event-1",
            "identity_key": identity,
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_CERTIFIED",
        },
    )


@pytest.mark.parametrize("missing_value", [None, "None", " none ", "", "NULL", "nan"])
def test_missing_validation_outcome_reaches_certified_interval_fallback(
    missing_value: object,
) -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000001"
    validation = (
        {
            "event_id": "event-1",
            "validation_outcome": missing_value,
            "bridge_certified_for_replay": None,
        },
    )

    intervals, summary = propagated_admission_intervals(
        coverage=_coverage(identity),
        factors=_factor(identity),
        validation_results=validation,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == (
        AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value
    )
    assert pre_event["future_bridge_validation_outcomes"] == []
    assert pre_event["future_unvalidated_certified_factor_count"] == 1
    assert summary["final_unresolved_interval_count"] == 0
    assert summary["implementation_defect_count"] == 0


def test_missing_outcome_does_not_bypass_uncertified_bridge() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000002"
    validation = (
        {
            "event_id": "event-1",
            "validation_outcome": "None",
            "bridge_dependency_state": "CROSS_ISIN_BRIDGE_REQUIRED",
            "bridge_certified_for_replay": False,
        },
    )

    intervals, summary = propagated_admission_intervals(
        coverage=_coverage(identity),
        factors=_factor(identity),
        validation_results=validation,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
    )
    assert summary["final_unresolved_interval_count"] == 0


def test_unknown_factor_with_string_none_remains_fail_closed() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000003"
    factors = (
        {
            "factor_id": "factor-unknown",
            "canonical_event_id": "event-1",
            "identity_key": identity,
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
        },
    )
    validation = ({"event_id": "event-1", "validation_outcome": "None"},)

    intervals, summary = propagated_admission_intervals(
        coverage=_coverage(identity),
        factors=factors,
        validation_results=validation,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == (
        AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    )
    assert summary["final_unresolved_interval_count"] == 0


def test_real_defect_remains_visible_and_counted() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000004"
    validation = (
        {
            "event_id": "event-1",
            "validation_outcome": "UNSUPPORTED_NEW_OUTCOME",
        },
    )

    intervals, summary = propagated_admission_intervals(
        coverage=_coverage(identity),
        factors=_factor(identity),
        validation_results=validation,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == AdmissionState.UNRESOLVED.value
    assert summary["final_unresolved_interval_count"] == 1
    assert summary["implementation_defect_count"] == 1
