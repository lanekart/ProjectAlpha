from __future__ import annotations

from decimal import Decimal

from alpha.strategy_lab.models import CombinationAttribution, LabStrategyResult


class CombinationAttributionEngine:
    """Explain whether apparent combination value is broad or concentration-driven."""

    def analyze(
        self,
        results: tuple[LabStrategyResult, ...],
        *,
        population_count: int,
    ) -> tuple[CombinationAttribution, ...]:
        rows: list[CombinationAttribution] = []
        for result in results:
            if len(result.strategy.conditions) < 2:
                continue
            metrics = result.metrics
            opportunity_reduction = (
                None
                if population_count <= 0
                else Decimal("100")
                - Decimal(metrics.signals_generated)
                / Decimal(population_count)
                * Decimal("100")
            )
            dominant = result.strategy.conditions[0].feature_name
            source, explanation = _source(result, opportunity_reduction)
            rows.append(
                CombinationAttribution(
                    strategy_id=result.strategy.strategy_id,
                    source=source,
                    dominant_component=dominant,
                    opportunity_reduction_pct=opportunity_reduction,
                    symbol_concentration_pct=metrics.symbol_concentration_pct,
                    period_concentration_pct=(
                        None
                        if metrics.positive_period_pct is None
                        else Decimal("100") - metrics.positive_period_pct
                    ),
                    winner_concentration_pct=(metrics.largest_winner_contribution_pct),
                    explanation=explanation,
                )
            )
        return tuple(rows)


def _source(
    result: LabStrategyResult,
    opportunity_reduction: Decimal | None,
) -> tuple[str, str]:
    metrics = result.metrics
    if metrics.completed_trades < 30:
        return "TINY_SAMPLE", "Apparent performance depends on fewer than 30 trades."
    if (
        metrics.largest_winner_contribution_pct is not None
        and metrics.largest_winner_contribution_pct > Decimal("40")
    ):
        return (
            "ONE_EXTREME_WINNER",
            "More than 40% of winning return comes from one trade.",
        )
    if (
        metrics.symbol_concentration_pct is not None
        and metrics.symbol_concentration_pct > Decimal("40")
    ):
        return "SYMBOL_CONCENTRATION", "More than 40% of trades come from one symbol."
    if opportunity_reduction is not None and opportunity_reduction > Decimal("90"):
        return (
            "OPPORTUNITY_ELIMINATION",
            "The combination removes more than 90% of the eligible population.",
        )
    if metrics.expectancy_pct is not None and metrics.expectancy_pct > Decimal("0"):
        return (
            "OUTCOME_IMPROVEMENT",
            "Positive net expectancy persists after explicit costs.",
        )
    return (
        "NO_CLEAR_VALUE",
        "The combination has no clearly supported net outcome advantage.",
    )


__all__ = ["CombinationAttributionEngine"]
