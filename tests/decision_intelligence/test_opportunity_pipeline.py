from __future__ import annotations

from decimal import Decimal

from alpha.decision_intelligence import (
    CapacityAssessment,
    InstitutionalCandidate,
    InstitutionalDecisionEngine,
    OpportunityGrade,
    SetupQualityScorecard,
)
from alpha.decision_intelligence.opportunity_pipeline import (
    OpportunityPipelineAction,
    OpportunityPipelineEngine,
    WatchlistReasonCode,
    render_opportunity_pipeline,
)


def test_extended_bullish_candidate_becomes_watchlist() -> None:
    candidate = _candidate(
        "TATVA",
        stop_distance=Decimal("12"),
        setup_stage="LATE",
        entry_ready=False,
        trigger_status="WAITING_FOR_PULLBACK",
        execution_status="WAIT FOR BETTER ENTRY",
        allocation_eligible=False,
    )

    institutional = InstitutionalDecisionEngine().evaluate((candidate,))
    pipeline = OpportunityPipelineEngine().build(institutional)

    assert not institutional.accepted_opportunities
    assert len(pipeline.watchlist_opportunities) == 1
    decision = pipeline.watchlist_opportunities[0]
    assert decision.action is OpportunityPipelineAction.WATCHLIST
    assert WatchlistReasonCode.ENTRY_EXTENDED in decision.watchlist_reasons
    assert WatchlistReasonCode.STOP_DISTANCE_TOO_WIDE in decision.watchlist_reasons
    assert decision.promotion_triggers


def test_poor_reward_risk_waits_for_better_asymmetry() -> None:
    candidate = _candidate("ASYM", reward_risk=Decimal("1.5"))

    pipeline = OpportunityPipelineEngine().build(
        InstitutionalDecisionEngine().evaluate((candidate,))
    )

    decision = pipeline.watchlist_opportunities[0]
    assert WatchlistReasonCode.UNFAVOURABLE_RISK_REWARD in decision.watchlist_reasons
    assert any("2R" in trigger.description for trigger in decision.promotion_triggers)


def test_weak_direction_is_not_admitted_to_watchlist() -> None:
    candidate = _candidate("WEAK", final_verdict="NEUTRAL")

    pipeline = OpportunityPipelineEngine().build(
        InstitutionalDecisionEngine().evaluate((candidate,))
    )

    assert not pipeline.watchlist_opportunities
    assert pipeline.rejected_opportunities[0].action is OpportunityPipelineAction.REJECT


def test_bad_data_is_not_admitted_to_watchlist() -> None:
    candidate = _candidate(
        "BADDATA",
        data_completeness="PARTIAL",
        stop_distance=Decimal("12"),
    )

    pipeline = OpportunityPipelineEngine().build(
        InstitutionalDecisionEngine().evaluate((candidate,))
    )

    assert not pipeline.watchlist_opportunities
    assert len(pipeline.rejected_opportunities) == 1


def test_accepted_candidate_remains_buy_ready() -> None:
    pipeline = OpportunityPipelineEngine().build(
        InstitutionalDecisionEngine().evaluate((_candidate("READY"),))
    )

    assert pipeline.buy_opportunities[0].action is OpportunityPipelineAction.BUY
    assert not pipeline.watchlist_opportunities


def test_watchlist_rendering_is_explicitly_non_executable() -> None:
    candidate = _candidate(
        "TATVA",
        setup_stage="LATE",
        entry_ready=False,
        trigger_status="WAITING_FOR_PULLBACK",
        execution_status="WAIT FOR BETTER ENTRY",
        allocation_eligible=False,
    )
    report = OpportunityPipelineEngine().build(
        InstitutionalDecisionEngine().evaluate((candidate,))
    )

    output = "\n".join(render_opportunity_pipeline(report))

    assert "TATVA: WATCHLIST (non-executable)" in output
    assert "Execution Readiness: NOT READY" in output
    assert "risk/reward or entry timing is unfavourable" in output
    assert "Promotion Triggers:" in output


def _candidate(
    symbol: str,
    *,
    final_verdict: str = "BUY",
    reward_risk: Decimal = Decimal("3"),
    stop_distance: Decimal = Decimal("6"),
    data_completeness: str = "COMPLETE",
    setup_stage: str = "ENTRY_READY",
    entry_ready: bool = True,
    trigger_status: str = "TRIGGER_CONFIRMED",
    execution_status: str = "BUY NOW",
    allocation_eligible: bool = True,
) -> InstitutionalCandidate:
    return InstitutionalCandidate(
        symbol=symbol,
        final_verdict=final_verdict,
        adjusted_confidence="HIGH",
        evidence_strength="moderate",
        final_score=Decimal("88"),
        reward_risk_ratio=reward_risk,
        stop_distance_percent=stop_distance,
        data_completeness=data_completeness,
        setup_quality="HIGH",
        sector="CHEMICALS",
        market_regime="BULLISH",
        sector_fit=Decimal("75"),
        portfolio_fit=Decimal("80"),
        posterior_probability=Decimal("0.70"),
        expectancy=Decimal("1.0"),
        entry=Decimal("100"),
        stop=Decimal("94"),
        target_1=Decimal("112"),
        target_2=Decimal("118"),
        target_3=Decimal("124"),
        capacity=CapacityAssessment(
            capacity_score=Decimal("90"),
            deployable_capital_estimate=Decimal("100000"),
            liquidity_warning=None,
            explanation="Capacity is supported by traded value.",
            data_sufficient=True,
        ),
        dma_20=Decimal("98"),
        atr=Decimal("4"),
        evidence_sample_count=80,
        setup_stage=setup_stage,
        entry_ready=entry_ready,
        trigger_status=trigger_status,
        execution_status=execution_status,
        allocation_eligible=allocation_eligible,
        setup_scorecard=SetupQualityScorecard(
            trend_alignment=Decimal("90"),
            price_volume_confirmation=Decimal("85"),
            entry_quality=Decimal("70"),
            stop_quality=Decimal("70"),
            target_realism=Decimal("75"),
            reward_risk_quality=Decimal("75"),
            historical_evidence=Decimal("70"),
            liquidity_capacity=Decimal("90"),
            market_regime_fit=Decimal("80"),
            total_score=Decimal("82"),
            setup_grade=OpportunityGrade.A,
            summary="Strong bullish setup with governed execution readiness.",
        ),
        historical_bar_count=1260,
    )
