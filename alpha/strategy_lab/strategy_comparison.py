from __future__ import annotations

from decimal import Decimal

from alpha.strategy_lab.models import LabStrategyResult, StrategyComparison


class StrategyComparisonEngine:
    """Compare strategies on their shared source population and selected trades."""

    def compare(
        self,
        results: tuple[LabStrategyResult, ...],
        strategy_ids: tuple[str, ...],
        *,
        shared_population: int,
    ) -> StrategyComparison:
        selected = tuple(
            item for item in results if item.strategy.strategy_id in set(strategy_ids)
        )
        if len(selected) < 2:
            raise ValueError("comparison requires at least two known strategy ids")
        ordered = tuple(
            sorted(
                selected, key=lambda item: strategy_ids.index(item.strategy.strategy_id)
            )
        )
        baseline = ordered[0]
        id_sets = [set(item.selected_candidate_ids) for item in ordered]
        common = set.intersection(*id_sets) if id_sets else set()
        return StrategyComparison(
            strategy_ids=tuple(item.strategy.strategy_id for item in ordered),
            rule_definitions={
                item.strategy.strategy_id: tuple(
                    condition.canonical_key for condition in item.strategy.conditions
                )
                or (item.strategy.family,)
                for item in ordered
            },
            shared_population=shared_population,
            common_trade_count=len(common),
            unique_trade_counts={
                item.strategy.strategy_id: len(
                    set(item.selected_candidate_ids)
                    - set().union(
                        *(
                            set(other.selected_candidate_ids)
                            for other in ordered
                            if other.strategy.strategy_id != item.strategy.strategy_id
                        )
                    )
                )
                for item in ordered
            },
            precision_deltas={
                item.strategy.strategy_id: _delta(
                    item.metrics.precision_pct, baseline.metrics.precision_pct
                )
                for item in ordered
            },
            expectancy_deltas={
                item.strategy.strategy_id: _delta(
                    item.metrics.expectancy_pct, baseline.metrics.expectancy_pct
                )
                for item in ordered
            },
            drawdown_deltas={
                item.strategy.strategy_id: _delta(
                    item.metrics.maximum_drawdown_pct,
                    baseline.metrics.maximum_drawdown_pct,
                )
                for item in ordered
            },
            capital_utilisation_deltas={
                item.strategy.strategy_id: _delta(
                    item.metrics.capital_utilisation_pct,
                    baseline.metrics.capital_utilisation_pct,
                )
                for item in ordered
            },
            cost_sensitivity_pct={
                item.strategy.strategy_id: item.metrics.net_cost_drag_pct
                for item in ordered
            },
            yearly_expectancy_deltas={
                item.strategy.strategy_id: _yearly_delta(item, baseline)
                for item in ordered
            },
            evidence_confidence="LOW_RECONSTRUCTED",
            conclusion=(
                "Differences are associative reconstructed evidence; no causal or "
                "deployment inference is permitted."
            ),
        )


def _delta(value: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    return None if value is None or baseline is None else value - baseline


def _yearly_delta(
    item: LabStrategyResult,
    baseline: LabStrategyResult,
) -> tuple[tuple[str, Decimal | None], ...]:
    baseline_by_period = {
        row.period: row.expectancy_pct for row in baseline.timeline.annual
    }
    return tuple(
        (
            row.period,
            _delta(row.expectancy_pct, baseline_by_period.get(row.period)),
        )
        for row in item.timeline.annual
    )


__all__ = ["StrategyComparisonEngine"]
