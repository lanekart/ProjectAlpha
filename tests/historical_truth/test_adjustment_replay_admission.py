from __future__ import annotations

from datetime import date

from alpha.historical_truth.adjustment_replay_admission_engine import (
    adjusted_replay_readiness,
    classify_factor_case,
    indicator_lookback_safety,
    mixed_basis_resolutions,
    quarantine_census,
    replay_admission_intervals,
    unknown_factor_impact,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
    MixedBasisResolution,
    ReplayImpact,
    ReplayReadiness,
    ValidationOutcome,
)

IDENTITY = "nse:isin:INE000A01001"


def _event(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_event_id": "event:one",
        "identity_key": IDENTITY,
        "symbol": "ALPHA",
        "series": "EQ",
        "isin": "INE000A01001",
        "action_type": "SPLIT",
        "effective_date": "2020-01-09",
        "series_applicability": ["EQ"],
    }
    row.update(changes)
    return row


def _factor(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": "event:one",
        "identity_key": IDENTITY,
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        "price_factor": 0.5,
        "quantity_factor": 2.0,
        "effective_date": "2020-01-09",
    }
    row.update(changes)
    return row


def _coverage() -> dict[str, object]:
    return {
        "identity_key": IDENTITY,
        "symbol": "ALPHA",
        "series": "EQ",
        "isin": "INE000A01001",
        "expected_identity_sessions": 100,
    }


def test_genuine_residual_market_gap_confirms_factor() -> None:
    case = {
        "case_id": "case:one",
        "event_id": "event:one",
        "identity_key": IDENTITY,
        "adjusted_gap_pct": 3.5,
    }
    result = classify_factor_case(
        case,
        {"event:one": _event()},
        {"event:one": _factor()},
        {"event:one": {"adjusted_gap_pct": 3.5}},
    )
    assert (
        result["validation_outcome"]
        == ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value
    )
    assert result["admitted_to_replay"] is True


def test_unknown_rights_factor_requires_certified_factor() -> None:
    rows = unknown_factor_impact(
        (_event(action_type="RIGHTS"),),
        (_factor(factor_state="FACTOR_UNKNOWN_MISSING_TERMS", price_factor=None),),
    )
    assert rows[0]["replay_impact"] == ReplayImpact.REQUIRE_CERTIFIED_FACTOR.value
    assert rows[0]["unknown_factor_applied_as_one"] is False


def test_non_multiplicative_transition_segments_identity() -> None:
    rows = unknown_factor_impact(
        (_event(action_type="MERGER"),),
        (_factor(factor_state="FACTOR_NOT_MULTIPLICATIVE", price_factor=None),),
    )
    assert (
        rows[0]["replay_impact"]
        == ReplayImpact.IDENTITY_TRANSITION_NONCOMPARABLE.value
    )


def test_mixed_basis_with_unknown_factor_is_segmented() -> None:
    rows = mixed_basis_resolutions(
        (
            {
                "identity_key": IDENTITY,
                "price_basis_state": "MIXED_PRICE_BASIS",
            },
        ),
        (
            {
                "identity_key": IDENTITY,
                "symbol": "ALPHA",
                "raw_row_count": 100,
                "adjusted_row_count": 50,
            },
        ),
        (
            _factor(factor_state="FACTOR_UNKNOWN_MISSING_TERMS"),
        ),
        (),
    )
    assert (
        rows[0]["resolution_state"]
        == MixedBasisResolution.ADJUSTED_WITH_SEGMENTED_UNCERTIFIED_INTERVAL.value
    )
    assert rows[0]["silent_mixed_basis"] is False


def test_quarantine_census_deduplicates_same_reason_and_interval() -> None:
    basis = (
        {
            "identity_key": IDENTITY,
            "price_basis_state": "FACTOR_UNKNOWN",
            "start_date": "2020-01-09",
            "end_date": "2020-01-09",
        },
        {
            "identity_key": IDENTITY,
            "price_basis_state": "FACTOR_UNKNOWN",
            "start_date": "2020-01-09",
            "end_date": "2020-01-09",
        },
    )
    rows = quarantine_census(
        basis=basis,
        summaries=(
            {
                "identity_key": IDENTITY,
                "raw_row_count": 100,
                "adjusted_row_count": 0,
            },
        ),
        results=(),
        unknown_impact_rows=(),
        mixed_rows=(),
    )
    assert len(rows) == 1
    assert rows[0]["affected_candle_rows"] == 100


def test_no_action_identity_is_raw_replay_certified() -> None:
    rows = replay_admission_intervals(
        coverage=(_coverage(),),
        basis=(),
        factors=(),
        mixed_rows=(),
        unknown_rows=(),
        start_date=date(2016, 1, 1),
        end_date=date(2026, 7, 20),
    )
    assert (
        rows[0]["admission_state"]
        == AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE.value
    )


def test_unknown_rights_factor_is_quarantined_from_replay() -> None:
    rows = replay_admission_intervals(
        coverage=(_coverage(),),
        basis=(
            {
                "identity_key": IDENTITY,
                "price_basis_state": "FACTOR_UNKNOWN",
                "start_date": "2020-01-09",
            },
        ),
        factors=(
            _factor(factor_state="FACTOR_UNKNOWN_MISSING_TERMS"),
        ),
        mixed_rows=(),
        unknown_rows=(
            {
                "identity_key": IDENTITY,
                "replay_impact": ReplayImpact.REQUIRE_CERTIFIED_FACTOR.value,
            },
        ),
        start_date=date(2016, 1, 1),
        end_date=date(2026, 7, 20),
    )
    assert (
        rows[0]["admission_state"]
        == AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    )


def test_segment_boundary_resets_all_indicator_lookbacks() -> None:
    admission = (
        {
            "identity_key": IDENTITY,
            "start_date": "2020-01-01",
            "admission_state": AdmissionState.SEGMENT_BOUNDARY_REQUIRED.value,
        },
    )
    rows = indicator_lookback_safety(admission, (14, 20, 50, 200))
    assert len(rows) == 4
    assert all(row["reset_required"] for row in rows)
    assert all(row["safety_state"] == "SAFE_AFTER_RESET" for row in rows)


def test_explicit_quarantine_can_be_conditionally_ready() -> None:
    admission = (
        {
            "identity_key": IDENTITY,
            "admission_state": AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value,
        },
    )
    readiness = adjusted_replay_readiness(admission, (), ())
    assert (
        readiness["state"]
        == ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
    )
    assert readiness["unknown_factor_applied_as_one"] is False
