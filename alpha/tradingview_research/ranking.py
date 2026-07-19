"""Evidence-only ranking of TRL experiments."""

from __future__ import annotations

from decimal import Decimal

from alpha.tradingview_research.comparison import ComparativeResearchEngine
from alpha.tradingview_research.models import (
    ComparisonReport,
    PromotionAssessment,
    PromotionDecision,
    RankedCandidate,
    TradingViewExperiment,
)
from alpha.tradingview_research.promotion import CandidatePromotionEngine


class CandidateRankingEngine:
    """Rank measured candidates without synthesizing an arbitrary score."""

    def __init__(self) -> None:
        self.comparison_engine = ComparativeResearchEngine()
        self.promotion_engine = CandidatePromotionEngine()

    def rank(
        self,
        experiments: tuple[TradingViewExperiment, ...],
    ) -> tuple[RankedCandidate, ...]:
        rows: list[
            tuple[TradingViewExperiment, ComparisonReport, PromotionAssessment]
        ] = []
        for experiment in experiments:
            comparison = self.comparison_engine.compare(experiment)
            promotion = self.promotion_engine.assess(experiment, comparison)
            rows.append((experiment, comparison, promotion))
        ordered = sorted(
            rows,
            key=lambda row: (
                row[2].decision is PromotionDecision.PROMOTE_TO_ALPHA_REPLAY,
                row[1].improved_cohorts,
                row[1].weighted_expectancy_improvement
                if row[1].weighted_expectancy_improvement is not None
                else Decimal("-Infinity"),
                row[1].weighted_drawdown_improvement
                if row[1].weighted_drawdown_improvement is not None
                else Decimal("-Infinity"),
                row[0].experiment_id,
            ),
            reverse=True,
        )
        return tuple(
            RankedCandidate(
                rank=index,
                experiment_id=experiment.experiment_id,
                promotion_decision=promotion.decision,
                matched_cohorts=len(comparison.cohorts),
                improved_cohorts=comparison.improved_cohorts,
                weighted_expectancy_improvement=(
                    comparison.weighted_expectancy_improvement
                ),
                weighted_drawdown_improvement=(
                    comparison.weighted_drawdown_improvement
                ),
                primary_rejection=(
                    promotion.failed_reasons[0] if promotion.failed_reasons else None
                ),
            )
            for index, (experiment, comparison, promotion) in enumerate(
                ordered, start=1
            )
        )
