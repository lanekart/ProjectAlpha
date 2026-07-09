from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.explainability.models import (
    ConfidenceLevel,
    ExplainabilityBullet,
    ExplainabilityReport,
    ExplainabilitySection,
    RecommendationExplanation,
)
from alpha.market_intelligence import (
    IntelligenceBias,
    MarketIntelligenceReport,
)
from alpha.portfolio_intelligence import (
    AllocationDecision,
    AllocationReport,
    CapitalAllocationPlan,
)
from alpha.recommendation_intelligence import (
    RecommendationDecision,
    RecommendationReport,
)


@dataclass(frozen=True, slots=True)
class IntelligenceExplainabilityEngine:
    """Build structured explanations from completed intelligence runs.

    This engine must remain downstream of computation. It does not score,
    allocate, rank, or override any domain decision. It only turns existing
    immutable reports into structured narrative primitives.
    """

    def explain(
        self,
        *,
        observed_on: str,
        market_report: MarketIntelligenceReport,
        recommendations: tuple[RecommendationReport, ...],
        allocation_plan: CapitalAllocationPlan,
    ) -> ExplainabilityReport:
        allocation_by_symbol = {
            report.symbol: report for report in allocation_plan.reports
        }
        recommendation_explanations = tuple(
            self._recommendation_explanation(
                recommendation=recommendation,
                allocation=allocation_by_symbol.get(recommendation.symbol),
            )
            for recommendation in recommendations
        )

        return ExplainabilityReport(
            title="Project Alpha Intelligence Explainability",
            observed_on=observed_on,
            confidence=self._overall_confidence(
                market_report=market_report,
                recommendations=recommendations,
            ),
            executive_summary=self._executive_summary(
                market_report=market_report,
                recommendations=recommendations,
                allocation_plan=allocation_plan,
            ),
            sections=(
                self._market_section(market_report),
                self._portfolio_section(allocation_plan),
            ),
            recommendations=recommendation_explanations,
            metadata={"version": "1"},
        )

    def _executive_summary(
        self,
        *,
        market_report: MarketIntelligenceReport,
        recommendations: tuple[RecommendationReport, ...],
        allocation_plan: CapitalAllocationPlan,
    ) -> tuple[ExplainabilityBullet, ...]:
        top_recommendation = recommendations[0] if recommendations else None
        allocation_count = len(allocation_plan.approved_reports)

        bullets = [
            ExplainabilityBullet(
                label="Market Bias",
                detail=market_report.bias.value,
                score=market_report.composite_score,
            ),
            ExplainabilityBullet(
                label="Capital Deployment",
                detail=f"{allocation_count} approved allocation(s)",
                score=allocation_plan.total_allocated_weight,
            ),
        ]

        if top_recommendation is not None:
            bullets.append(
                ExplainabilityBullet(
                    label="Top Recommendation",
                    detail=(
                        f"{top_recommendation.symbol} "
                        f"{top_recommendation.decision.value}"
                    ),
                    score=top_recommendation.score,
                )
            )

        return tuple(bullets)

    def _market_section(
        self,
        market_report: MarketIntelligenceReport,
    ) -> ExplainabilitySection:
        bullets = tuple(
            ExplainabilityBullet(label="Market Reason", detail=reason)
            for reason in market_report.reasons
        )

        return ExplainabilitySection(
            title="Market Intelligence Reasons",
            bullets=bullets,
        )

    def _portfolio_section(
        self,
        allocation_plan: CapitalAllocationPlan,
    ) -> ExplainabilitySection:
        bullets = tuple(
            ExplainabilityBullet(label="Portfolio Reason", detail=reason)
            for reason in allocation_plan.reasons
        )

        return ExplainabilitySection(
            title="Portfolio Allocation Reasons",
            bullets=bullets,
        )

    def _recommendation_explanation(
        self,
        *,
        recommendation: RecommendationReport,
        allocation: AllocationReport | None,
    ) -> RecommendationExplanation:
        allocation_decision = (
            allocation.decision.value
            if allocation is not None
            else AllocationDecision.SKIP.value
        )
        allocation_weight = (
            allocation.target_weight if allocation is not None else Decimal("0")
        )

        return RecommendationExplanation(
            symbol=recommendation.symbol,
            decision=recommendation.decision.value,
            action=recommendation.action.value,
            confidence=self._recommendation_confidence(recommendation),
            score=recommendation.score,
            allocation_decision=allocation_decision,
            allocation_weight=allocation_weight,
            primary_drivers=self._primary_drivers(recommendation),
            primary_risks=self._primary_risks(recommendation),
            portfolio_reasons=self._portfolio_reasons(allocation),
        )

    def _primary_drivers(
        self,
        recommendation: RecommendationReport,
    ) -> tuple[ExplainabilityBullet, ...]:
        bullets = [
            ExplainabilityBullet(
                label=evidence.label,
                detail=evidence.rationale,
                score=evidence.score_points,
            )
            for evidence in recommendation.supporting_evidence
        ]

        bullets.extend(
            (
                ExplainabilityBullet(
                    label="Recommendation Score",
                    detail=f"{recommendation.score}/100",
                    score=recommendation.score,
                ),
                ExplainabilityBullet(
                    label="Expected Value",
                    detail=(
                        "return "
                        f"{recommendation.expected_value.expected_return}; "
                        "drawdown "
                        f"{recommendation.expected_value.expected_drawdown}"
                    ),
                    score=recommendation.expected_value.score,
                ),
            )
        )

        return tuple(bullets)

    def _primary_risks(
        self,
        recommendation: RecommendationReport,
    ) -> tuple[ExplainabilityBullet, ...]:
        return tuple(
            ExplainabilityBullet(
                label=risk.label,
                detail=risk.rationale,
                score=risk.penalty_points,
            )
            for risk in recommendation.opposing_evidence
        )

    def _portfolio_reasons(
        self,
        allocation: AllocationReport | None,
    ) -> tuple[ExplainabilityBullet, ...]:
        if allocation is None:
            return (
                ExplainabilityBullet(
                    label="Portfolio Decision",
                    detail="No allocation report was produced.",
                ),
            )

        return tuple(
            ExplainabilityBullet(
                label="Portfolio Decision",
                detail=reason,
                score=allocation.target_weight,
            )
            for reason in allocation.reasons
        )

    def _overall_confidence(
        self,
        *,
        market_report: MarketIntelligenceReport,
        recommendations: tuple[RecommendationReport, ...],
    ) -> ConfidenceLevel:
        if market_report.bias is IntelligenceBias.NEGATIVE:
            return ConfidenceLevel.LOW

        if not recommendations:
            return ConfidenceLevel.LOW

        top_score = recommendations[0].score
        if top_score >= Decimal("80"):
            return ConfidenceLevel.HIGH
        if top_score >= Decimal("60"):
            return ConfidenceLevel.MODERATE
        return ConfidenceLevel.LOW

    def _recommendation_confidence(
        self,
        recommendation: RecommendationReport,
    ) -> ConfidenceLevel:
        if recommendation.decision in {
            RecommendationDecision.STRONG_BUY,
            RecommendationDecision.BUY,
        }:
            return ConfidenceLevel.HIGH
        if recommendation.decision is RecommendationDecision.WATCHLIST:
            return ConfidenceLevel.MODERATE
        return ConfidenceLevel.LOW


__all__ = ["IntelligenceExplainabilityEngine"]
