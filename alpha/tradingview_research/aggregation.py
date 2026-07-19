"""Sector and universe aggregation for measured TRL observations."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median

from alpha.tradingview_research.comparison import ComparativeResearchEngine
from alpha.tradingview_research.models import (
    ComparisonOutcome,
    DistributionStatistic,
    ExperimentObservation,
    ObservationRole,
    ResearchPartition,
    SectorResearchSummary,
    TradingViewExperiment,
    UniverseDistribution,
)


class ResearchAggregationEngine:
    """Aggregate observed evidence without hiding missing measurements."""

    def sector_summaries(
        self,
        experiment: TradingViewExperiment,
    ) -> tuple[SectorResearchSummary, ...]:
        comparison = ComparativeResearchEngine().compare(experiment)
        treatments = {
            item.population_key: item
            for item in experiment.observations
            if item.role is ObservationRole.TREATMENT
        }
        grouped: dict[
            tuple[ResearchPartition, str],
            list[tuple[ExperimentObservation, ComparisonOutcome]],
        ] = defaultdict(list)
        for cohort in comparison.cohorts:
            treatment = treatments[cohort.population_key]
            grouped[(treatment.partition, treatment.sector)].append(
                (treatment, cohort.outcome)
            )
        summaries = []
        for (partition, sector), rows in sorted(
            grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            observations = tuple(item[0] for item in rows)
            outcomes = tuple(item[1] for item in rows)
            summaries.append(
                SectorResearchSummary(
                    partition=partition,
                    sector=sector,
                    symbols=tuple(sorted({item.symbol for item in observations})),
                    matched_cohorts=len(observations),
                    treatment_trades=sum(
                        item.metrics.trade_count for item in observations
                    ),
                    win_rate_pct=self._weighted_metric(observations, "win_rate_pct"),
                    profit_factor=self._weighted_metric(observations, "profit_factor"),
                    expectancy=self._weighted_metric(observations, "expectancy"),
                    recommendation=self._combined_outcome(outcomes),
                )
            )
        return tuple(summaries)

    def universe_distribution(
        self,
        experiment: TradingViewExperiment,
        *,
        role: ObservationRole,
        partition: ResearchPartition,
    ) -> UniverseDistribution:
        observations = tuple(
            item
            for item in experiment.observations
            if item.role is role and item.partition is partition
        )
        return UniverseDistribution(
            partition=partition,
            role=role,
            symbols=tuple(sorted({item.symbol for item in observations})),
            observations=len(observations),
            trade_count=sum(item.metrics.trade_count for item in observations),
            win_rate_pct=self._distribution(observations, "win_rate_pct"),
            profit_factor=self._distribution(observations, "profit_factor"),
            expectancy=self._distribution(observations, "expectancy"),
        )

    def _weighted_metric(
        self,
        observations: tuple[ExperimentObservation, ...],
        metric: str,
    ) -> Decimal | None:
        values = tuple(
            (getattr(item.metrics, metric), item.metrics.trade_count)
            for item in observations
        )
        if not values or any(value is None or weight == 0 for value, weight in values):
            return None
        total_weight = sum(weight for _, weight in values)
        if total_weight == 0:
            return None
        return sum(
            (
                value * Decimal(weight)
                for value, weight in values
                if isinstance(value, Decimal)
            ),
            start=Decimal("0"),
        ) / Decimal(total_weight)

    def _distribution(
        self,
        observations: tuple[ExperimentObservation, ...],
        metric: str,
    ) -> DistributionStatistic:
        values = sorted(
            value
            for item in observations
            if isinstance((value := getattr(item.metrics, metric)), Decimal)
        )
        available = len(values)
        count = len(observations)
        return DistributionStatistic(
            observation_count=count,
            available_count=available,
            missing_count=count - available,
            minimum=values[0] if values else None,
            median=Decimal(median(values)) if values else None,
            maximum=values[-1] if values else None,
        )

    def _combined_outcome(
        self,
        outcomes: tuple[ComparisonOutcome, ...],
    ) -> ComparisonOutcome:
        if not outcomes or ComparisonOutcome.INSUFFICIENT_EVIDENCE in outcomes:
            return ComparisonOutcome.INSUFFICIENT_EVIDENCE
        if ComparisonOutcome.WORSE in outcomes:
            return ComparisonOutcome.WORSE
        if all(item is ComparisonOutcome.IMPROVED for item in outcomes):
            return ComparisonOutcome.IMPROVED
        return ComparisonOutcome.UNCHANGED
