"""Population-matched comparison of measured TRL evidence."""

from __future__ import annotations

from decimal import Decimal

from alpha.tradingview_research.models import (
    CohortComparison,
    ComparisonOutcome,
    ComparisonReport,
    ExperimentObservation,
    MetricDelta,
    ObservationRole,
    TradingViewExperiment,
)


class ComparativeResearchEngine:
    """Compare treatment with baseline only on identical observed cohorts."""

    def compare(self, experiment: TradingViewExperiment) -> ComparisonReport:
        baseline = {
            item.population_key: item
            for item in experiment.observations
            if item.role is ObservationRole.ALPHA_BASELINE
        }
        treatment = {
            item.population_key: item
            for item in experiment.observations
            if item.role is ObservationRole.TREATMENT
        }
        shared = tuple(sorted(set(baseline) & set(treatment)))
        cohorts = tuple(
            self._compare_cohort(baseline[key], treatment[key]) for key in shared
        )
        return ComparisonReport(
            experiment_id=experiment.experiment_id,
            cohorts=cohorts,
            unmatched_baseline_cohorts=len(set(baseline) - set(treatment)),
            unmatched_treatment_cohorts=len(set(treatment) - set(baseline)),
            improved_cohorts=sum(
                item.outcome is ComparisonOutcome.IMPROVED for item in cohorts
            ),
            unchanged_cohorts=sum(
                item.outcome is ComparisonOutcome.UNCHANGED for item in cohorts
            ),
            worse_cohorts=sum(
                item.outcome is ComparisonOutcome.WORSE for item in cohorts
            ),
            insufficient_cohorts=sum(
                item.outcome is ComparisonOutcome.INSUFFICIENT_EVIDENCE
                for item in cohorts
            ),
            weighted_expectancy_improvement=self._weighted_delta(cohorts, "expectancy"),
            weighted_drawdown_improvement=self._weighted_delta(
                cohorts, "maximum_drawdown_pct"
            ),
        )

    def _compare_cohort(
        self,
        baseline: ExperimentObservation,
        treatment: ExperimentObservation,
    ) -> CohortComparison:
        baseline_metrics = baseline.metrics
        treatment_metrics = treatment.metrics
        deltas = (
            self._delta(
                "trade_count",
                baseline_metrics.trade_count,
                treatment_metrics.trade_count,
            ),
            self._delta(
                "win_rate_pct",
                baseline_metrics.win_rate_pct,
                treatment_metrics.win_rate_pct,
            ),
            self._delta(
                "profit_factor",
                baseline_metrics.profit_factor,
                treatment_metrics.profit_factor,
            ),
            self._delta(
                "expectancy",
                baseline_metrics.expectancy,
                treatment_metrics.expectancy,
            ),
            self._delta(
                "maximum_drawdown_pct",
                baseline_metrics.maximum_drawdown_pct,
                treatment_metrics.maximum_drawdown_pct,
                higher_is_better=False,
            ),
            self._delta(
                "net_return_pct",
                baseline_metrics.net_return_pct,
                treatment_metrics.net_return_pct,
            ),
            self._delta(
                "average_winner",
                baseline_metrics.average_winner,
                treatment_metrics.average_winner,
            ),
            self._delta(
                "average_loser",
                baseline_metrics.average_loser,
                treatment_metrics.average_loser,
            ),
        )
        expectancy = next(item for item in deltas if item.metric == "expectancy")
        drawdown = next(
            item for item in deltas if item.metric == "maximum_drawdown_pct"
        )
        outcome = self._outcome(expectancy, drawdown)
        return CohortComparison(
            population_key=baseline.population_key,
            baseline_trades=baseline_metrics.trade_count,
            treatment_trades=treatment_metrics.trade_count,
            deltas=deltas,
            outcome=outcome,
        )

    def _delta(
        self,
        metric: str,
        baseline: Decimal | int | None,
        treatment: Decimal | int | None,
        *,
        higher_is_better: bool = True,
    ) -> MetricDelta:
        improvement: Decimal | int | None = None
        if baseline is not None and treatment is not None:
            improvement = (
                treatment - baseline if higher_is_better else baseline - treatment
            )
        return MetricDelta(
            metric=metric,
            baseline=baseline,
            treatment=treatment,
            improvement=improvement,
            higher_is_better=higher_is_better,
        )

    def _outcome(
        self,
        expectancy: MetricDelta,
        drawdown: MetricDelta,
    ) -> ComparisonOutcome:
        if expectancy.improvement is None or drawdown.improvement is None:
            return ComparisonOutcome.INSUFFICIENT_EVIDENCE
        if expectancy.improvement > 0 and drawdown.improvement >= 0:
            return ComparisonOutcome.IMPROVED
        if expectancy.improvement == 0 and drawdown.improvement == 0:
            return ComparisonOutcome.UNCHANGED
        return ComparisonOutcome.WORSE

    def _weighted_delta(
        self,
        cohorts: tuple[CohortComparison, ...],
        metric: str,
    ) -> Decimal | None:
        measured: list[tuple[Decimal, int]] = []
        for cohort in cohorts:
            delta = cohort.delta(metric)
            if (
                delta is None
                or delta.improvement is None
                or cohort.treatment_trades == 0
            ):
                return None
            measured.append((Decimal(delta.improvement), cohort.treatment_trades))
        total_weight = sum(weight for _, weight in measured)
        if not measured or total_weight == 0:
            return None
        return sum(
            (value * Decimal(weight) for value, weight in measured),
            start=Decimal("0"),
        ) / Decimal(total_weight)
