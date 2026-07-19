from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

from alpha.adaptive_weights.models import (
    AlphaComponent,
    ComponentDecisionState,
    ComponentWeightDecision,
    ContributionEstimate,
    EvidencePartition,
    PolicyComparison,
    PromotionDecision,
    RedundancyClass,
    StabilityAssessment,
    StabilityClass,
)
from alpha.adaptive_weights.overlap_analysis import IndicatorOverlapEngine
from alpha.adaptive_weights.promotion import CandidateWeightPromotionEngine
from alpha.adaptive_weights.stability_analysis import ContributionStabilityEngine
from tests.adaptive_weights.helpers import completed_evidence, performance


def test_overlap_matrix_detects_same_source_and_redundant_scores() -> None:
    evidence = tuple(
        completed_evidence(
            index,
            score_overrides={
                AlphaComponent.PRICE_STRUCTURE: Decimal(index % 10) / Decimal("10"),
                AlphaComponent.TREND: Decimal(index % 10) / Decimal("10"),
            },
            lineage_overrides={
                AlphaComponent.PRICE_STRUCTURE: "close_and_moving_averages.v1",
                AlphaComponent.TREND: "close_and_moving_averages.v1",
            },
        )
        for index in range(20)
    )
    findings = IndicatorOverlapEngine().analyze(evidence)
    pair = next(
        item
        for item in findings
        if item.component_a is AlphaComponent.PRICE_STRUCTURE
        and item.component_b is AlphaComponent.TREND
    )
    assert pair.redundancy_class is RedundancyClass.SAME_SOURCE
    assert pair.score_correlation == Decimal("1")
    assert pair.shared_source_lineage is True


def test_component_that_only_works_for_breakouts_is_conditional() -> None:
    evidence = []
    for index in range(40):
        score = Decimal(index % 10) / Decimal("10")
        is_breakout = index < 20
        evidence.append(
            completed_evidence(
                index,
                partition=(
                    EvidencePartition.HOLDOUT
                    if is_breakout
                    else EvidencePartition.DEVELOPMENT
                ),
                setup="BREAKOUT" if is_breakout else "PULLBACK",
                score_overrides={AlphaComponent.RETRACEMENT: score},
                realised_r=(score - Decimal("0.5"))
                * (Decimal("1") if is_breakout else Decimal("-1")),
            )
        )
    contribution = tuple(
        ContributionEstimate(
            component=component,
            standalone_contribution=Decimal("0.1"),
            marginal_contribution=Decimal("0.1"),
            conditional_contribution=Decimal("0.5"),
            leave_one_out_contribution=Decimal("0.1"),
            permutation_importance=Decimal("0.1"),
            confidence_interval_low=Decimal("-0.1"),
            confidence_interval_high=Decimal("0.3"),
            sample_size=40,
            completed_partition_count=2,
            partition_contributions=MappingProxyType(
                {"DEVELOPMENT": Decimal("0.1"), "HOLDOUT": Decimal("0.1")}
            ),
            method_label="fixture",
        )
        for component in AlphaComponent
    )
    assessments = ContributionStabilityEngine().analyze(tuple(evidence), contribution)
    retracement = next(
        item for item in assessments if item.component is AlphaComponent.RETRACEMENT
    )
    assert retracement.setup_stability == Decimal("0.5")
    assert retracement.classification is StabilityClass.CONDITIONAL


def test_holdout_performance_failure_blocks_promotion() -> None:
    comparisons = tuple(
        PolicyComparison(
            baseline_policy="ALPHA_CANONICAL",
            candidate_policy="ALPHA_WEIGHT_RESEARCH_0001",
            partition=partition,
            baseline=performance(
                expectancy="0.2",
                win_rate="0.55",
                profit_factor="1.3",
                drawdown="8",
            ),
            candidate=performance(
                expectancy=(
                    "-0.1" if partition is EvidencePartition.HOLDOUT else "0.3"
                ),
                win_rate="0.56",
                profit_factor=(
                    "1.0" if partition is EvidencePartition.HOLDOUT else "1.4"
                ),
                drawdown="8",
            ),
            symbol_count=6,
            sector_count=3,
            setup_count=3,
        )
        for partition in (
            EvidencePartition.VALIDATION,
            EvidencePartition.HOLDOUT,
            EvidencePartition.FORWARD_OBSERVED,
        )
    )
    stabilities = tuple(_stable(component) for component in AlphaComponent)
    decisions = tuple(_maintain(component) for component in AlphaComponent)
    assessment = CandidateWeightPromotionEngine().assess(
        "ALPHA_WEIGHT_RESEARCH_0001",
        comparisons,
        stabilities,
        (),
        decisions,
    )
    assert assessment.decision is PromotionDecision.REJECT
    assert any("holdout expectancy" in blocker for blocker in assessment.blockers)


def _stable(component: AlphaComponent) -> StabilityAssessment:
    return StabilityAssessment(
        component=component,
        sample_size=100,
        directional_stability=Decimal("1"),
        magnitude_stability=Decimal("1"),
        rank_stability=Decimal("1"),
        sector_stability=Decimal("1"),
        setup_stability=Decimal("1"),
        regime_stability=Decimal("1"),
        horizon_stability=Decimal("1"),
        era_stability=Decimal("1"),
        holdout_consistency=True,
        forward_consistency=True,
        classification=StabilityClass.ROBUST,
        evidence_notes=(),
    )


def _maintain(component: AlphaComponent) -> ComponentWeightDecision:
    return ComponentWeightDecision(
        component=component,
        current_weight=Decimal("10"),
        proposed_raw_weight=Decimal("10"),
        proposed_weight=Decimal("10"),
        absolute_change=Decimal("0"),
        relative_change=Decimal("0"),
        payoff_multiplier=Decimal("1"),
        confidence_multiplier=Decimal("1"),
        stability_multiplier=Decimal("1"),
        uniqueness_multiplier=Decimal("1"),
        decision=ComponentDecisionState.MAINTAIN_WEIGHT,
        primary_reason="fixture",
        supporting_metrics=(),
        blocking_reasons=(),
    )
