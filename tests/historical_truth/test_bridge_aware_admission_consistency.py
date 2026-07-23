from __future__ import annotations

from datetime import date

from alpha.historical_truth.adjustment_replay_admission_models import AdmissionState
from alpha.historical_truth.bridge_aware_admission_consistency import (
    consistent_admission_intervals,
    consistent_readiness,
    corrected_residual_attribution,
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


def test_certified_unvalidated_factor_uses_explicit_state_fallback() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000001"
    factors = (
        {
            "factor_id": "non-material-certified",
            "canonical_event_id": "event-without-validation-row",
            "identity_key": identity,
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_CERTIFIED",
        },
    )

    intervals, summary = consistent_admission_intervals(
        coverage=_coverage(identity),
        factors=factors,
        validation_results=(),
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == (
        AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value
    )
    assert pre_event["future_unvalidated_certified_factor_count"] == 1
    assert summary["certified_unvalidated_factor_count"] == 1
    assert summary["unresolved_interval_count"] == 0


def test_unvalidated_unknown_factor_remains_quarantined() -> None:
    sessions = tuple(date(2026, 1, day) for day in range(1, 6))
    identity = "nse:isin:INE000000002"
    factors = (
        {
            "factor_id": "unknown",
            "canonical_event_id": "unknown-event",
            "identity_key": identity,
            "effective_date": "2026-01-03",
            "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
        },
    )

    intervals, summary = consistent_admission_intervals(
        coverage=_coverage(identity),
        factors=factors,
        validation_results=(),
        sessions=sessions,
        start_date=sessions[0],
        end_date=sessions[-1],
    )

    pre_event = next(row for row in intervals if row["start_date"] == "2026-01-01")
    assert pre_event["admission_state"] == (
        AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    )
    assert summary["noncertified_unvalidated_factor_count"] == 1
    assert summary["unresolved_interval_count"] == 0


def test_readiness_counts_refresh_after_quarantine_augmentation() -> None:
    intervals = (
        {
            "admission_state": AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value,
        },
        {
            "admission_state": AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT.value,
        },
    )
    residual = {
        "attribution_counts": {
            "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED": 1,
        }
    }

    readiness = consistent_readiness(
        base={
            "state": "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION",
            "blockers": ["UNCERTIFIED_CROSS_ISIN_BRIDGES"],
            "bridge_uncertified_count": 24,
            "admission_quarantined_identity_count": 47,
            "evidence_quarantined_identity_count": 283,
        },
        intervals=intervals,
        reporting={
            "admission_quarantined_identity_count": 24,
            "evidence_quarantined_identity_count": 30,
            "unresolved_case_identity_count": 0,
        },
        residual_summary=residual,
    )

    assert readiness["admission_quarantined_identity_count"] == 24
    assert readiness["evidence_quarantined_identity_count"] == 30
    assert readiness["quarantined_identity_count"] == 24
    assert readiness["bridge_uncertified_case_count"] == 24
    assert readiness["bridge_uncertified_count"] == 24
    assert readiness["residual_attribution_counts"] == residual["attribution_counts"]
    assert "UNRESOLVED_ADMISSION_INTERVALS" not in readiness["blockers"]


def test_unresolved_interval_is_fail_closed() -> None:
    readiness = consistent_readiness(
        base={
            "state": "CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION",
            "blockers": [],
            "bridge_uncertified_count": 0,
        },
        intervals=({"admission_state": AdmissionState.UNRESOLVED.value},),
        reporting={
            "admission_quarantined_identity_count": 1,
            "evidence_quarantined_identity_count": 1,
            "unresolved_case_identity_count": 1,
        },
        residual_summary={"attribution_counts": {}},
    )

    assert readiness["state"] == "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    assert "UNRESOLVED_ADMISSION_INTERVALS" in readiness["blockers"]


def test_corrected_residual_attribution_supersedes_b1c_labels() -> None:
    results = (
        {
            "bridge_aware_reconciliation_applied": True,
            "residual_attribution": "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED",
        },
        {
            "bridge_aware_reconciliation_applied": True,
            "residual_attribution": "BRIDGE_AWARE_FACTOR_CONFIRMED",
        },
        {
            "bridge_aware_reconciliation_applied": False,
            "residual_attribution": "NOT_APPLICABLE",
        },
    )

    summary = corrected_residual_attribution(results)

    assert summary["bridge_aware_corrected_case_count"] == 2
    assert summary["attribution_counts"] == {
        "BRIDGE_AWARE_FACTOR_CONFIRMED": 1,
        "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED": 1,
        "NOT_APPLICABLE": 1,
    }
    assert "UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECT" not in summary[
        "attribution_counts"
    ]
