"""Fail-closed TRL candidate promotion into Alpha replay only."""

from __future__ import annotations

from alpha.tradingview_research.models import (
    ComparisonReport,
    PromotionAssessment,
    PromotionDecision,
    PromotionReason,
    ResearchPartition,
    TradingViewExperiment,
)


class CandidatePromotionEngine:
    """Apply the declared evidence gates without inventing performance thresholds."""

    def assess(
        self,
        experiment: TradingViewExperiment,
        comparison: ComparisonReport,
    ) -> PromotionAssessment:
        failed: list[PromotionReason] = []
        partitions = {
            ResearchPartition(cohort.population_key[0]) for cohort in comparison.cohorts
        }
        required = {
            ResearchPartition.DEVELOPMENT: PromotionReason.MISSING_DEVELOPMENT,
            ResearchPartition.VALIDATION: PromotionReason.MISSING_VALIDATION,
            ResearchPartition.HOLDOUT: PromotionReason.MISSING_HOLDOUT,
        }
        failed.extend(
            reason
            for partition, reason in required.items()
            if partition not in partitions
        )
        if not comparison.cohorts or comparison.insufficient_cohorts:
            failed.append(PromotionReason.MISSING_COMPARABLE_METRICS)
        if any(cohort.treatment_trades == 0 for cohort in comparison.cohorts):
            failed.append(PromotionReason.NO_COMPLETED_TRADES)
        if any(
            (delta := cohort.delta("expectancy")) is None
            or delta.improvement is None
            or delta.improvement <= 0
            for cohort in comparison.cohorts
        ):
            failed.append(PromotionReason.EXPECTANCY_NOT_IMPROVED)
        if any(
            (delta := cohort.delta("maximum_drawdown_pct")) is None
            or delta.improvement is None
            or delta.improvement < 0
            for cohort in comparison.cohorts
        ):
            failed.append(PromotionReason.DRAWDOWN_WORSE)

        validation_keys = tuple(
            cohort.population_key
            for cohort in comparison.cohorts
            if cohort.population_key[0]
            in {ResearchPartition.VALIDATION.value, ResearchPartition.HOLDOUT.value}
        )
        if len({key[1] for key in validation_keys}) < 2:
            failed.append(PromotionReason.INSUFFICIENT_SYMBOL_DIVERSITY)
        if len({key[2] for key in validation_keys}) < 2:
            failed.append(PromotionReason.INSUFFICIENT_SECTOR_DIVERSITY)
        if not self._partitions_are_ordered(comparison):
            failed.append(PromotionReason.PARTITION_LEAKAGE)

        failed_reasons = tuple(dict.fromkeys(failed))
        if failed_reasons:
            return PromotionAssessment(
                experiment_id=experiment.experiment_id,
                decision=PromotionDecision.REJECT,
                promote=False,
                passed_reasons=(),
                failed_reasons=failed_reasons,
                explanation=(
                    "Reject. The configuration remains research evidence and cannot "
                    "enter Alpha replay until every declared gate passes."
                ),
            )
        return PromotionAssessment(
            experiment_id=experiment.experiment_id,
            decision=PromotionDecision.PROMOTE_TO_ALPHA_REPLAY,
            promote=True,
            passed_reasons=(PromotionReason.ALL_RESEARCH_GATES_PASSED,),
            failed_reasons=(),
            explanation=(
                "Promote only to Alpha replay and walk-forward validation. This is "
                "not approval for production or capital deployment."
            ),
        )

    def _partitions_are_ordered(self, comparison: ComparisonReport) -> bool:
        bounds: dict[ResearchPartition, tuple[str, str]] = {}
        for partition in ResearchPartition:
            keys = tuple(
                item.population_key
                for item in comparison.cohorts
                if item.population_key[0] == partition.value
            )
            if keys:
                bounds[partition] = (
                    min(key[3] for key in keys),
                    max(key[4] for key in keys),
                )
        if set(bounds) != set(ResearchPartition):
            return False
        return (
            bounds[ResearchPartition.DEVELOPMENT][1]
            < bounds[ResearchPartition.VALIDATION][0]
            and bounds[ResearchPartition.VALIDATION][1]
            < bounds[ResearchPartition.HOLDOUT][0]
        )
