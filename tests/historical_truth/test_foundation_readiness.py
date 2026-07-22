from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from alpha.historical_truth.foundation_readiness_engine import (
    conflict_cases,
    daily_contracts,
    join_population,
    readiness_decision,
    resolve_discrepancies,
    resolve_gaps,
    suspension_ceiling,
    termination_boundaries,
)
from alpha.historical_truth.foundation_readiness_models import (
    PRODUCTION_INFLUENCE,
    AmbiguityEffect,
    ConflictOutcome,
    ConflictResolution,
    FoundationReadiness,
    JoinReadiness,
    SuspensionCeiling,
    TerminationState,
)


def _overlap(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "conflict_id": "overlap:one",
        "identity_key": "nse:isin:INE000A01001",
        "support_state": "TIER_A_CORE_EQUITY",
        "same_isin": True,
        "same_series": False,
        "within_one_identity": True,
        "transition_event_ids": [],
    }
    row.update(changes)
    return row


def _observation(symbol: str = "ALPHA") -> dict[str, object]:
    return {
        "identity_key": "nse:isin:INE000A01001",
        "symbol": symbol,
        "series": "EQ",
        "isin": "INE000A01001",
        "security_name": "Alpha Limited",
    }


def _cases(overlap: dict[str, object]) -> tuple[object, object, object]:
    return conflict_cases(
        [overlap],
        {
            "overlap:one": {
                "conflict_id": "overlap:one",
                "left_value": "EQ",
                "right_value": "BE",
                "overlap_start": "2020-01-01",
                "overlap_end": "2020-12-31",
                "left_source_event_ids": [],
                "right_source_event_ids": [],
            }
        },
        {"nse:isin:INE000A01001": [_observation()]},
        {"nse:isin:INE000A01001": {}},
        {},
        {},
    )


def test_parallel_series_is_non_blocking_under_same_isin() -> None:
    cases, _, resolutions = _cases(_overlap())

    assert cases[0].conflict_type.value == "VALID_PARALLEL_SERIES"
    assert resolutions[0].outcome is ConflictOutcome.RESOLVED_PARALLEL_SERIES
    assert not resolutions[0].blocking


def test_different_isin_or_identity_is_quarantined() -> None:
    _, _, resolutions = _cases(_overlap(same_isin=False, within_one_identity=False))

    assert resolutions[0].blocking
    assert resolutions[0].excluded_from_certified_join


def test_gap_is_bounded_membership_ambiguity_not_identity_ambiguity() -> None:
    rows = resolve_gaps(
        [
            {
                "gap_id": "gap:one",
                "identity_key": "nse:isin:INE000A01001",
                "support_state": "TIER_A_CORE_EQUITY",
                "earliest_possible_effective_date": "2020-01-01",
                "latest_possible_effective_date": "2020-02-01",
            }
        ]
    )

    assert rows[0].effect is AmbiguityEffect.MEMBERSHIP_AMBIGUITY_ONLY
    assert rows[0].corporate_action_join_valid
    assert rows[0].earliest_possible_effective_date == date(2020, 1, 1)


@pytest.mark.parametrize(
    ("symbol", "state"),
    [
        ("HDFC", "RESOLVED_PREDECESSOR_TERMINATED"),
        ("ASTRAL", "RESOLVED_ISIN_TRANSITION"),
        ("CRISIL", "RESOLVED_ISIN_TRANSITION"),
        ("COX&KINGS", "RESOLVED_STALE_PREDECESSOR"),
        ("AMIORG", "RESOLVED_SYMBOL_TRANSITION"),
    ],
)
def test_named_2026_discrepancy_fixtures(symbol: str, state: str) -> None:
    rows = resolve_discrepancies(
        [
            {
                "symbol": symbol,
                "identity_key": f"identity:{symbol}",
                "derived_interval_state": "DERIVED_ACTIVE_PROVISIONAL",
                "checkpoint_state": "ABSENT",
                "source_evidence": ["fixture:official"],
            }
        ]
    )

    assert rows[0].final_state == state
    assert not rows[0].parity_should_hold


def test_amiorg_uses_explicit_official_symbol_event() -> None:
    row = resolve_discrepancies(
        [
            {
                "symbol": "AMIORG",
                "identity_key": "nse:isin:INE00FF01017",
                "derived_interval_state": "ACTIVE",
                "checkpoint_state": "ABSENT",
                "source_evidence": [],
            }
        ]
    )[0]

    assert row.event_date == date(2025, 6, 2)
    assert any("ACUTAAS" in item for item in row.source_evidence)


def test_active_later_checkpoint_is_not_missing_termination() -> None:
    rows = termination_boundaries(
        [{"identity_key": "id", "support_state": "TIER_A_CORE_EQUITY"}],
        {"id": {"identity_key": "id", "current_active": True}},
        {"id": [{"symbol": "ALPHA"}]},
        {},
    )

    assert rows[0].state is TerminationState.ACTIVE_AT_LATER_CHECKPOINT
    assert not rows[0].affects_corporate_action_join


def test_exact_termination_wins_over_candle_observation() -> None:
    rows = termination_boundaries(
        [{"identity_key": "id", "support_state": "TIER_A_CORE_EQUITY"}],
        {
            "id": {
                "identity_key": "id",
                "exact_termination_date": "2020-04-01",
                "final_canonical_candle": "2020-03-30",
            }
        },
        {"id": [{"symbol": "ALPHA"}]},
        {},
    )

    assert rows[0].exact_date == date(2020, 4, 1)
    assert rows[0].state is TerminationState.EXACT_TERMINATION


def test_merger_predecessor_is_not_unresolved_cessation() -> None:
    rows = termination_boundaries(
        [{"identity_key": "id", "support_state": "TIER_A_CORE_EQUITY"}],
        {"id": {"identity_key": "id"}},
        {"id": [{"symbol": "ALPHA"}]},
        {"id": [{"transition_id": "transition:one"}]},
    )

    assert rows[0].state is TerminationState.MERGER_OR_SCHEME_PREDECESSOR


def test_no_official_cessation_remains_unresolved() -> None:
    row = termination_boundaries(
        [{"identity_key": "id", "support_state": "TIER_A_CORE_EQUITY"}],
        {"id": {"identity_key": "id", "final_canonical_candle": "2020-01-01"}},
        {"id": [{"symbol": "ALPHA"}]},
        {},
    )[0]

    assert row.state is TerminationState.GENUINELY_UNRESOLVED_CESSATION
    assert row.exact_date is None


def test_suspension_evidence_ceiling_is_partial_and_non_membership_blocking() -> None:
    ceiling = suspension_ceiling(
        [
            {
                "source_id": "current-workbook",
                "evidence_type": "SUSPENSION_AND_RESTORATION",
                "failure_code": None,
            },
            {
                "source_id": "historical-archive",
                "evidence_type": "SUSPENSION_AND_RESTORATION",
                "failure_code": "NOT_FOUND",
            },
        ]
    )[0]

    assert ceiling.state is SuspensionCeiling.HISTORICAL_SUSPENSION_PARTIAL
    assert ceiling.acquired_sources == 1
    assert ceiling.failed_sources == 1
    assert ceiling.permanent_known_limitation
    assert not ceiling.membership_blocking


def test_activity_source_contract_prohibits_identity_inferences() -> None:
    contract = daily_contracts(
        [
            {
                "source_family": "NSE_CM_UDIFF_BHAVCOPY",
                "covered_from": "2024-07-08",
                "covered_to": "2026-07-20",
                "format_name": "UDiFF",
                "inclusion_contract": "REPORTABLE_ACTIVITY_ONLY",
                "zero_volume_rows": 0,
                "suspended_security_behavior": "UNRESOLVED",
                "confidence": "MEDIUM",
            }
        ]
    )[0]

    assert not contract.membership_inference_allowed
    assert not contract.suspension_inference_allowed
    assert not contract.termination_inference_allowed
    assert contract.trading_activity_evidence_allowed
    assert contract.candle_computation_allowed


def _certification(identity: str = "id") -> dict[str, str]:
    return {"identity_key": identity, "support_state": "TIER_A_CORE_EQUITY"}


def test_bounded_gap_identity_remains_join_ready() -> None:
    gaps = resolve_gaps(
        [
            {
                "gap_id": "gap:one",
                "identity_key": "id",
                "support_state": "TIER_A_CORE_EQUITY",
                "earliest_possible_effective_date": "2020-01-01",
                "latest_possible_effective_date": "2020-02-01",
            }
        ]
    )
    join = join_population([_certification()], {"id": [_observation()]}, gaps, ())[0]

    assert join.state is JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP
    assert join.admitted_to_certified_join


def test_blocking_identity_is_quarantined_from_denominator() -> None:
    conflict = ConflictResolution(
        "case",
        "id",
        ConflictOutcome.QUARANTINED_IDENTITY_DATE_AMBIGUITY,
        True,
        False,
        True,
        6,
        "fixture",
    )
    join = join_population(
        [_certification()], {"id": [_observation()]}, (), (conflict,)
    )[0]

    assert join.state is JoinReadiness.QUARANTINED_IDENTITY_AMBIGUITY
    assert not join.admitted_to_certified_join


def test_readiness_is_conditional_when_quarantine_is_explicit() -> None:
    conflict = ConflictResolution(
        "case",
        "id",
        ConflictOutcome.RETAINED_NON_BLOCKING_OFFICIAL_CONFLICT,
        False,
        True,
        False,
        2,
        "fixture",
    )
    joins = join_population([_certification()], {"id": [_observation()]}, (), ())
    quarantined = replace(
        joins[0],
        state=JoinReadiness.QUARANTINED_IDENTITY_AMBIGUITY,
        admitted_to_certified_join=False,
    )

    decision = readiness_decision((quarantined,), (conflict,), ())

    assert decision.state is FoundationReadiness.CONDITIONALLY_READY_FOR_HTR_010B


def test_governance_is_diagnostic_only() -> None:
    assert PRODUCTION_INFLUENCE is False
