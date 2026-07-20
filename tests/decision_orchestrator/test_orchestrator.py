from __future__ import annotations

from decimal import Decimal
import json

import pytest

from alpha.decision_lifecycle import LifecycleState
from alpha.decision_orchestrator import (
    AdvisorAuthority,
    AdvisorSignal,
    DecisionContext,
    DecisionOrchestrator,
    export_orchestrated_decision_json,
    render_orchestrated_decision,
)


def _signal(
    source: str,
    state: LifecycleState,
    *,
    authority: AdvisorAuthority = AdvisorAuthority.PRIMARY,
    confidence: str = "0.8",
    veto: bool = False,
) -> AdvisorSignal:
    return AdvisorSignal(
        source=source,
        proposed_state=state,
        authority=authority,
        confidence=Decimal(confidence),
        reason=f"{source} recommends {state.value}",
        evidence_ids=(f"{source}_EVIDENCE",),
        veto=veto,
    )


def test_higher_authority_signal_wins_conflict() -> None:
    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-1",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal("PIPELINE", LifecycleState.READY),
            _signal(
                "GOVERNANCE",
                LifecycleState.WATCHLIST,
                authority=AdvisorAuthority.GOVERNANCE,
            ),
        ),
    )

    assert decision.final_state is LifecycleState.WATCHLIST
    assert decision.winning_source == "GOVERNANCE"
    assert decision.dissenting_sources == ("PIPELINE",)


def test_veto_limits_winner_selection_to_veto_signals() -> None:
    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-2",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal(
                "PIPELINE",
                LifecycleState.READY,
                authority=AdvisorAuthority.HARD_RISK,
            ),
            _signal(
                "REGIME",
                LifecycleState.WATCHLIST,
                authority=AdvisorAuthority.CONTEXT,
                veto=True,
            ),
        ),
    )

    assert decision.final_state is LifecycleState.WATCHLIST
    assert decision.winning_source == "REGIME"


def test_position_exit_precedes_reduce_at_equal_authority() -> None:
    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-3",
        symbol="abc",
        context=DecisionContext.ACTIVE_POSITION,
        signals=(
            _signal("POSITION", LifecycleState.REDUCE),
            _signal("STOP", LifecycleState.EXIT),
        ),
    )

    assert decision.final_state is LifecycleState.EXIT
    assert decision.urgency_score == 100


def test_candidate_state_is_rejected_for_position_context() -> None:
    with pytest.raises(ValueError, match="invalid for ACTIVE_POSITION"):
        DecisionOrchestrator().decide(
            recommendation_id="rec-4",
            symbol="abc",
            context=DecisionContext.ACTIVE_POSITION,
            signals=(_signal("PIPELINE", LifecycleState.READY),),
        )


def test_buy_requires_execution_confirmation_authority() -> None:
    with pytest.raises(ValueError, match="execution-confirmation"):
        DecisionOrchestrator().decide(
            recommendation_id="rec-5",
            symbol="abc",
            context=DecisionContext.EXECUTION,
            signals=(_signal("USER", LifecycleState.BUY),),
        )

    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-5",
        symbol="abc",
        context=DecisionContext.EXECUTION,
        signals=(
            _signal(
                "EXECUTION_LEDGER",
                LifecycleState.BUY,
                authority=AdvisorAuthority.EXECUTION_CONFIRMATION,
            ),
        ),
    )
    assert decision.final_state is LifecycleState.BUY


def test_duplicate_sources_fail_closed() -> None:
    with pytest.raises(ValueError, match="sources must be unique"):
        DecisionOrchestrator().decide(
            recommendation_id="rec-6",
            symbol="abc",
            context=DecisionContext.CANDIDATE,
            signals=(
                _signal("PIPELINE", LifecycleState.READY),
                _signal("pipeline", LifecycleState.WATCHLIST),
            ),
        )


def test_supporting_evidence_and_confidence_are_aggregated() -> None:
    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-7",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal("PIPELINE", LifecycleState.READY, confidence="0.9"),
            _signal("STRESS", LifecycleState.READY, confidence="0.7"),
            _signal("REGIME", LifecycleState.WATCHLIST, confidence="0.4"),
        ),
        stability_score=75,
    )

    assert decision.supporting_sources == ("PIPELINE", "STRESS")
    assert decision.evidence_ids == ("PIPELINE_EVIDENCE", "STRESS_EVIDENCE")
    assert decision.confidence_score == 80
    assert decision.stability_score == 75


def test_rendering_and_json_are_deterministic() -> None:
    decision = DecisionOrchestrator().decide(
        recommendation_id="rec-8",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal("PIPELINE", LifecycleState.READY),
            _signal("REGIME", LifecycleState.WATCHLIST),
        ),
        stability_score=60,
    )

    assert render_orchestrated_decision(decision) == (
        "Alpha Authoritative Decision",
        "Symbol: ABC",
        "Context: CANDIDATE",
        "Final State: READY",
        "Confidence: 50/100",
        "Urgency: 55/100",
        "Winning Source: PIPELINE",
        "Supporting Sources: PIPELINE",
        "Dissenting Sources: REGIME",
        "Stability: 60/100",
        "Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE",
    )
    payload = json.loads(export_orchestrated_decision_json(decision))
    assert payload["final_state"] == "READY"
    assert payload["trace"][0]["source"] == "PIPELINE"
    assert payload["production_influence"] is False


def test_invalid_signal_metadata_fails_closed() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _signal("PIPELINE", LifecycleState.READY, confidence="1.1")
    with pytest.raises(ValueError, match="evidence ids"):
        AdvisorSignal(
            source="PIPELINE",
            proposed_state=LifecycleState.READY,
            authority=AdvisorAuthority.PRIMARY,
            confidence=Decimal("0.8"),
            reason="Valid reason",
            evidence_ids=(),
        )
