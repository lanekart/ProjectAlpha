from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from alpha.decision_lifecycle import LifecycleState
from alpha.decision_orchestrator import (
    AdvisorAuthority,
    AdvisorSignal,
    DecisionContext,
    GovernedDecisionFlow,
)
from alpha.decision_science import DecisionStabilityEngine, StabilityScenario
from alpha.governance import (
    EvidenceCategory,
    EvidenceMaturity,
    EvidenceMetadata,
    EvidenceRegistry,
    EvidenceStatus,
    GovernancePolicy,
)


def _metadata(
    evidence_id: str,
    *,
    maturity: EvidenceMaturity = EvidenceMaturity.FORWARD_VALIDATED,
    status: EvidenceStatus = EvidenceStatus.ACTIVE,
) -> EvidenceMetadata:
    return EvidenceMetadata(
        evidence_id=evidence_id,
        display_name=evidence_id,
        provider="TEST",
        category=EvidenceCategory.OTHER,
        version="1.0",
        owner="ALPHA",
        maturity=maturity,
        status=status,
        replay_verified=maturity >= EvidenceMaturity.REPLAY_VERIFIED,
        minimum_sample_size=10,
        current_sample_size=10,
        last_validation=(
            date(2026, 7, 20)
            if maturity >= EvidenceMaturity.FORWARD_VALIDATED
            else None
        ),
    )


def _signal(
    source: str,
    state: LifecycleState,
    evidence_id: str,
    *,
    authority: AdvisorAuthority = AdvisorAuthority.PRIMARY,
    veto: bool = False,
) -> AdvisorSignal:
    return AdvisorSignal(
        source=source,
        proposed_state=state,
        authority=authority,
        confidence=Decimal("0.8"),
        reason=f"{source} recommends {state.value}",
        evidence_ids=(evidence_id,),
        veto=veto,
    )


def test_allowed_evidence_reaches_orchestrator() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry((_metadata("PIPELINE_EVIDENCE"),)),
        policy=GovernancePolicy.production(),
    )

    result = flow.evaluate(
        recommendation_id="rec-1",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(_signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),),
    )

    assert result.decision.final_state is LifecycleState.READY
    assert result.signal_assessments[0].included is True
    assert result.transition is None


def test_diagnostic_evidence_is_downgraded_and_cannot_veto() -> None:
    registry = EvidenceRegistry(
        (
            _metadata("PIPELINE_EVIDENCE"),
            _metadata(
                "REGIME_EVIDENCE",
                maturity=EvidenceMaturity.REPLAY_VERIFIED,
            ),
        )
    )
    flow = GovernedDecisionFlow(
        registry=registry,
        policy=GovernancePolicy.production(),
    )

    result = flow.evaluate(
        recommendation_id="rec-2",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),
            _signal(
                "REGIME",
                LifecycleState.WATCHLIST,
                "REGIME_EVIDENCE",
                authority=AdvisorAuthority.HARD_RISK,
                veto=True,
            ),
        ),
    )

    assessment = result.signal_assessments[1]
    assert assessment.effective_authority is AdvisorAuthority.CONTEXT
    assert assessment.diagnostic_evidence_ids == ("REGIME_EVIDENCE",)
    assert result.decision.final_state is LifecycleState.READY


def test_blocked_or_unregistered_evidence_excludes_signal() -> None:
    registry = EvidenceRegistry(
        (
            _metadata("PIPELINE_EVIDENCE"),
            _metadata(
                "SUSPENDED_EVIDENCE",
                status=EvidenceStatus.SUSPENDED,
            ),
        )
    )
    flow = GovernedDecisionFlow(
        registry=registry,
        policy=GovernancePolicy.production(),
    )

    result = flow.evaluate(
        recommendation_id="rec-3",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(
            _signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),
            _signal("RISK", LifecycleState.AVOID, "SUSPENDED_EVIDENCE"),
            _signal("UNKNOWN", LifecycleState.AVOID, "UNKNOWN_EVIDENCE"),
        ),
    )

    assert result.decision.final_state is LifecycleState.READY
    assert result.signal_assessments[1].included is False
    assert result.signal_assessments[2].included is False


def test_all_blocked_signals_fail_closed() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry(),
        policy=GovernancePolicy.production(),
    )

    with pytest.raises(ValueError, match="all advisor signals were blocked"):
        flow.evaluate(
            recommendation_id="rec-4",
            symbol="abc",
            context=DecisionContext.CANDIDATE,
            signals=(_signal("PIPELINE", LifecycleState.READY, "UNKNOWN_EVIDENCE"),),
        )


def test_stability_score_flows_into_authoritative_decision() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry((_metadata("PIPELINE_EVIDENCE"),)),
        policy=GovernancePolicy.production(),
    )
    stability = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.READY,
        scenarios=(
            StabilityScenario(
                scenario_id="PRICE_MINUS_1",
                description="Price falls one percent",
                resulting_state=LifecycleState.READY,
            ),
            StabilityScenario(
                scenario_id="REGIME_MINUS_10",
                description="Regime confidence falls",
                resulting_state=LifecycleState.WATCHLIST,
            ),
        ),
    )

    result = flow.evaluate(
        recommendation_id="rec-5",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(_signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),),
        stability=stability,
    )

    assert result.decision.stability_score == 50


def test_authoritative_decision_records_legal_lifecycle_transition() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry((_metadata("PIPELINE_EVIDENCE"),)),
        policy=GovernancePolicy.production(),
    )

    result = flow.evaluate(
        recommendation_id="rec-6",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(_signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),),
        previous_state=LifecycleState.WATCHLIST,
        occurred_at=datetime(2026, 7, 20, 9, 15, tzinfo=UTC),
    )

    assert result.transition is not None
    assert result.transition.previous_state is LifecycleState.WATCHLIST
    assert result.transition.new_state is LifecycleState.READY
    assert result.transition.evidence[0].code == "PIPELINE_EVIDENCE"


def test_unchanged_state_does_not_append_transition() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry((_metadata("PIPELINE_EVIDENCE"),)),
        policy=GovernancePolicy.production(),
    )

    result = flow.evaluate(
        recommendation_id="rec-7",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        signals=(_signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),),
        previous_state=LifecycleState.READY,
        occurred_at=datetime(2026, 7, 20, 9, 15, tzinfo=UTC),
    )

    assert result.transition is None
    assert flow.lifecycle.repository.all() == ()


def test_transition_timestamp_is_required_for_state_change() -> None:
    flow = GovernedDecisionFlow(
        registry=EvidenceRegistry((_metadata("PIPELINE_EVIDENCE"),)),
        policy=GovernancePolicy.production(),
    )

    with pytest.raises(ValueError, match="occurred_at is required"):
        flow.evaluate(
            recommendation_id="rec-8",
            symbol="abc",
            context=DecisionContext.CANDIDATE,
            signals=(_signal("PIPELINE", LifecycleState.READY, "PIPELINE_EVIDENCE"),),
            previous_state=LifecycleState.WATCHLIST,
        )
