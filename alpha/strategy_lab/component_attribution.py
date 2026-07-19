from __future__ import annotations

from decimal import Decimal

from alpha.strategy_lab.indicator_registry import IndicatorRegistry
from alpha.strategy_lab.models import (
    AttributionClassification,
    ComponentAttribution,
    LabStrategyResult,
)


class ComponentAttributionEngine:
    """Compare matched rules with and without one component when available."""

    def __init__(self, indicators: IndicatorRegistry | None = None) -> None:
        self.indicators = indicators or IndicatorRegistry()

    def analyze(
        self, results: tuple[LabStrategyResult, ...]
    ) -> tuple[ComponentAttribution, ...]:
        by_conditions = {
            frozenset(item.canonical_key for item in result.strategy.conditions): result
            for result in results
        }
        definitions = {item.canonical_id: item for item in self.indicators.definitions}
        rows: list[ComponentAttribution] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            conditions = frozenset(
                item.canonical_key for item in result.strategy.conditions
            )
            for condition in result.strategy.conditions:
                identity = (result.strategy.strategy_id, condition.feature_name)
                if identity in seen:
                    continue
                seen.add(identity)
                baseline = by_conditions.get(conditions - {condition.canonical_key})
                definition = definitions.get(condition.feature_name)
                overlap = () if definition is None else definition.lineage_overlaps
                selected_features = {
                    item.feature_name for item in result.strategy.conditions
                }
                lineage_warning = (
                    "Same-source lineage overlap prevents causal attribution."
                    if selected_features & set(overlap)
                    else None
                )
                rows.append(
                    _attribution(
                        component=condition.feature_name,
                        result=result,
                        baseline=baseline,
                        lineage_warning=lineage_warning,
                    )
                )
        return tuple(
            sorted(rows, key=lambda item: (item.component_id, item.strategy_id))
        )


def _attribution(
    *,
    component: str,
    result: LabStrategyResult,
    baseline: LabStrategyResult | None,
    lineage_warning: str | None,
) -> ComponentAttribution:
    if baseline is None:
        return ComponentAttribution(
            component_id=component,
            strategy_id=result.strategy.strategy_id,
            baseline_strategy_id=None,
            trade_count_delta=0,
            precision_delta_pct=None,
            expectancy_delta_pct=None,
            profit_factor_delta=None,
            payoff_delta=None,
            drawdown_delta_pct=None,
            capital_utilisation_delta_pct=None,
            turnover_delta=0,
            classification=AttributionClassification.INSUFFICIENT_EVIDENCE,
            lineage_warning=lineage_warning,
            evidence=("No otherwise-identical ablation strategy was generated.",),
        )
    current = result.metrics
    control = baseline.metrics
    expectancy = _delta(current.expectancy_pct, control.expectancy_pct)
    precision = _delta(current.precision_pct, control.precision_pct)
    profit_factor = _delta(current.profit_factor, control.profit_factor)
    payoff = _delta(current.payoff_ratio, control.payoff_ratio)
    drawdown = _delta(current.maximum_drawdown_pct, control.maximum_drawdown_pct)
    capital = _delta(current.capital_utilisation_pct, control.capital_utilisation_pct)
    if lineage_warning is not None:
        classification = AttributionClassification.LINEAGE_CONFOUNDED
    elif current.completed_trades < 30 or control.completed_trades < 30:
        classification = AttributionClassification.INSUFFICIENT_EVIDENCE
    elif expectancy is not None and expectancy > Decimal("0.10"):
        classification = AttributionClassification.POSITIVE_MARGINAL_VALUE
    elif expectancy is not None and expectancy < Decimal("-0.10"):
        classification = AttributionClassification.NEGATIVE_MARGINAL_VALUE
    elif expectancy is not None and abs(expectancy) <= Decimal("0.10"):
        classification = AttributionClassification.REDUNDANT
    else:
        classification = AttributionClassification.UNSTABLE
    return ComponentAttribution(
        component_id=component,
        strategy_id=result.strategy.strategy_id,
        baseline_strategy_id=baseline.strategy.strategy_id,
        trade_count_delta=current.completed_trades - control.completed_trades,
        precision_delta_pct=precision,
        expectancy_delta_pct=expectancy,
        profit_factor_delta=profit_factor,
        payoff_delta=payoff,
        drawdown_delta_pct=drawdown,
        capital_utilisation_delta_pct=capital,
        turnover_delta=current.turnover - control.turnover,
        classification=classification,
        lineage_warning=lineage_warning,
        evidence=(
            "Matched strategy comparison uses the same source dataset and "
            "execution profile.",
            "Classification is associative, not causal.",
        ),
    )


def _delta(value: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    return None if value is None or baseline is None else value - baseline


__all__ = ["ComponentAttributionEngine"]
