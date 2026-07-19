from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from alpha.adaptive_weights.models import (
    AblationContribution,
    AblationObservation,
    AblationRole,
    AlphaComponent,
    EvidenceQuality,
    ResearchPerformance,
)

_MATCHING_DEFINITION = (
    "exact symbol, date, strategy, setup, stop, exit, cost, dataset, partition"
)


class MatchedAblationEngine:
    def analyze(
        self, observations: tuple[AblationObservation, ...]
    ) -> tuple[AblationContribution, ...]:
        grouped: dict[
            tuple[AlphaComponent, tuple[str, ...]],
            dict[AblationRole, list[AblationObservation]],
        ] = defaultdict(lambda: defaultdict(list))
        for observation in observations:
            grouped[(observation.component, observation.match_key)][
                observation.role
            ].append(observation)

        pairs: dict[
            AlphaComponent,
            list[tuple[ResearchPerformance, ResearchPerformance]],
        ] = defaultdict(list)
        for (component, _), roles in grouped.items():
            with_items = sorted(
                roles.get(AblationRole.WITH_COMPONENT, []),
                key=lambda item: item.research_id,
            )
            without_items = sorted(
                roles.get(AblationRole.WITHOUT_COMPONENT, []),
                key=lambda item: item.research_id,
            )
            for with_item, without_item in zip(with_items, without_items, strict=False):
                pairs[component].append(
                    (with_item.performance, without_item.performance)
                )

        return tuple(
            self._summarize(component, pairs[component]) for component in AlphaComponent
        )

    def _summarize(
        self,
        component: AlphaComponent,
        pairs: list[tuple[ResearchPerformance, ResearchPerformance]],
    ) -> AblationContribution:
        count = len(pairs)
        if not pairs:
            return AblationContribution(
                component=component,
                matched_cohort_count=0,
                expectancy_with_component=None,
                expectancy_without_component=None,
                delta_expectancy=None,
                delta_win_rate=None,
                delta_average_winner_r=None,
                delta_average_loser_r=None,
                delta_profit_factor=None,
                delta_drawdown=None,
                delta_trade_count=None,
                delta_holding_period=None,
                evidence_quality=EvidenceQuality.INSUFFICIENT,
                matching_definition=_MATCHING_DEFINITION,
            )
        with_performance = [item[0] for item in pairs]
        without_performance = [item[1] for item in pairs]
        with_expectancy = _mean(item.expectancy for item in with_performance)
        without_expectancy = _mean(item.expectancy for item in without_performance)
        profit_factor_pairs = [
            (with_item.profit_factor, without_item.profit_factor)
            for with_item, without_item in pairs
            if with_item.profit_factor is not None
            and without_item.profit_factor is not None
        ]
        quality = EvidenceQuality.SUFFICIENT if count >= 5 else EvidenceQuality.WEAK
        return AblationContribution(
            component=component,
            matched_cohort_count=count,
            expectancy_with_component=with_expectancy,
            expectancy_without_component=without_expectancy,
            delta_expectancy=with_expectancy - without_expectancy,
            delta_win_rate=_mean(item.win_rate for item in with_performance)
            - _mean(item.win_rate for item in without_performance),
            delta_average_winner_r=_mean(
                item.average_winner_r for item in with_performance
            )
            - _mean(item.average_winner_r for item in without_performance),
            delta_average_loser_r=_mean(
                item.average_loser_r for item in with_performance
            )
            - _mean(item.average_loser_r for item in without_performance),
            delta_profit_factor=_mean(
                item[0] for item in profit_factor_pairs if item[0] is not None
            )
            - _mean(item[1] for item in profit_factor_pairs if item[1] is not None)
            if profit_factor_pairs
            else None,
            delta_drawdown=_mean(item.max_drawdown for item in with_performance)
            - _mean(item.max_drawdown for item in without_performance),
            delta_trade_count=sum(item.trade_count for item in with_performance)
            - sum(item.trade_count for item in without_performance),
            delta_holding_period=_mean(
                item.average_holding_period for item in with_performance
            )
            - _mean(item.average_holding_period for item in without_performance),
            evidence_quality=quality,
            matching_definition=_MATCHING_DEFINITION,
        )


def _mean(values: Iterable[Decimal]) -> Decimal:
    materialized = tuple(values)
    if not materialized:
        return Decimal("0")
    return sum(materialized, start=Decimal("0")) / Decimal(len(materialized))


__all__ = ["MatchedAblationEngine"]
