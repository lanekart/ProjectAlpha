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


def _run(
    identity: str,
    validation: tuple[dict[str, object], ...],
    *,
    factors: tuple[dict[str, object], ...] | None = None,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    return propagated_admission_intervals(
        coverage=_coverage(identity),
        factors=factors or _factor(identity),
        validation_results=validation,
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )


def _pre_event(
    intervals: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return next(row for row in intervals if row["start_date"] == "2026-01-01")


@pytest.mark.parametrize("missing_value", [None, "None", " none ", "", "NULL", "nan"])
def test_missing_validation_outcome_reaches_certified_interval_fallback(
    missing_value: object,
) -> None:
    identity = "nse:isin:INE000000001"
    intervals, summary = _run(
        identity,
        (
            {
                "event_id": "event-1",
                "validation_outcome": missing_value,
                "bridge_certified_for_replay": None,
            },
        ),
    )

    pre_event = _pre_event(intervals)
    assert pre_event["admission_state"] == (
        AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value
    )
    assert pre_event["future_bridge_validation_outcomes"] == []
    assert pre_event["future_unvalidated_certified_factor_count"] == 1
    assert summary["final_unresolved_interval_count"] == 0
    assert summary["implementation_defect_count"] == 0


def test_missing_outcome_does_not_bypass_uncertified_bridge() -> None:
    identity = "nse:isin:INE000000002"
    intervals, summary = _run(
        identity,
        (
            {
                "event_id": "event-1",
                "validation_outcome": "None",
                "bridge_dependency_state": "CROSS_ISIN_BRIDGE_REQUIRED",
                "bridge_certified_for_replay": False,
            },
        ),
    )

    assert _pre_event(intervals)["admission_state"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
    )
    assert summary["final_unresolved_interval_count"] == 0


def test_unknown_factor_with_string_none_remains_fail_closed() -> None:
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
    intervals, summary = _run(
        identity,
        ({"event_id": "event-1", "validation_outcome": "None"},),
        factors=factors,
    )

    assert _pre_event(intervals)["admission_state"] == (
        AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    )
    assert summary["final_unresolved_interval_count"] == 0


def test_reference_price_requirement_is_explicitly_fail_closed() -> None:
    identity = "nse:isin:INE000000004"
    intervals, summary = _run(
        identity,
        (
            {
                "event_id": "event-1",
                "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
            },
        ),
    )

    pre_event = _pre_event(intervals)
    assert pre_event["admission_state"] == (
        AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    )
    assert pre_event["admitted_price_view"] == "NONE"
    assert summary["validation_reference_price_row_count"] == 1
    assert summary["final_unresolved_interval_count"] == 0
    assert summary["implementation_defect_count"] == 0


def test_reference_price_requirement_cannot_bypass_uncertified_bridge() -> None:
    identity = "nse:isin:INE000000005"
    intervals, summary = _run(
        identity,
        (
            {
                "event_id": "event-1",
                "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
                "bridge_dependency_state": "CROSS_ISIN_BRIDGE_REQUIRED",
                "bridge_certified_for_replay": False,
            },
        ),
    )

    assert _pre_event(intervals)["admission_state"] == (
        AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value
    )
    assert summary["final_unresolved_interval_count"] == 0


def test_real_defect_remains_visible_and_counted() -> None:
    identity = "nse:isin:INE000000006"
    intervals, summary = _run(
        identity,
        (
            {
                "event_id": "event-1",
                "validation_outcome": "UNSUPPORTED_NEW_OUTCOME",
            },
        ),
    )

    assert _pre_event(intervals)["admission_state"] == AdmissionState.UNRESOLVED.value
    assert summary["final_unresolved_interval_count"] == 1
    assert summary["implementation_defect_count"] == 1
