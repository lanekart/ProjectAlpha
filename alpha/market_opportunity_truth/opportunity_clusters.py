from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from alpha.market_opportunity_truth.models import (
    MarketOpportunity,
    OpportunityClusterSummary,
    OpportunitySeed,
    TrendState,
    VolatilityState,
)

_TWO = Decimal("0.01")


def assign_natural_cluster(seed: OpportunitySeed) -> tuple[str, str]:
    """Assign geometry-based families without Alpha setup labels or outcomes."""

    trade = seed.tradability
    volume = trade.relative_volume or Decimal("0")
    base = trade.base_depth_percent
    extension = trade.extension_percent
    if (
        base is not None
        and base <= 12
        and trade.volatility_state
        in {
            VolatilityState.LOW,
            VolatilityState.NORMAL,
        }
    ):
        return (
            "TIGHT_GEOMETRY",
            "Narrow point-in-time base with low or normal ATR volatility.",
        )
    if volume >= Decimal("2"):
        return (
            "VOLUME_EXPANSION",
            "Relative volume is at least 2x its point-in-time average.",
        )
    if (
        trade.trend_state is TrendState.UP_ALIGNED
        and extension is not None
        and extension <= 3
    ):
        return (
            "ALIGNED_CONTINUATION",
            "Price and moving averages are aligned with limited extension.",
        )
    if trade.volatility_state in {VolatilityState.ELEVATED, VolatilityState.HIGH}:
        return (
            "VOLATILE_RESOLUTION",
            "The onset resolves while ATR volatility is elevated or high.",
        )
    if base is not None and base > 20:
        return (
            "WIDE_BASE_RESOLUTION",
            "The point-in-time consolidation depth exceeds 20 percent.",
        )
    if trade.liquidity_turnover is not None and trade.liquidity_turnover >= Decimal(
        "100000000"
    ):
        return (
            "LIQUID_RANGE_RESOLUTION",
            "Average traded value exceeds INR 100 million.",
        )
    return (
        "BALANCED_RESOLUTION",
        "No dominant geometry, volume, trend, volatility, or liquidity trait.",
    )


def cluster_summaries(
    opportunities: tuple[MarketOpportunity, ...],
) -> tuple[OpportunityClusterSummary, ...]:
    grouped: dict[str, list[MarketOpportunity]] = defaultdict(list)
    for item in opportunities:
        grouped[item.cluster_id].append(item)
    total = len(opportunities)
    rows = []
    for cluster_id, values in sorted(grouped.items()):
        mature = tuple(
            item
            for item in values
            if item.target_before_stop is not None
            and item.mfe_percent is not None
            and item.mae_percent is not None
        )
        rows.append(
            OpportunityClusterSummary(
                cluster_id=cluster_id,
                opportunities=len(values),
                institutional_quality=sum(
                    item.quality.institutional for item in values
                ),
                population_percent=_rate(len(values), total) or Decimal("0.00"),
                median_prospective_rr=_median(
                    tuple(item.prospective_rr for item in values)
                ),
                mature_outcomes=len(mature),
                target_before_stop_rate=_rate(
                    sum(item.target_before_stop is True for item in mature),
                    len(mature),
                ),
                average_realized_r=_mean(
                    tuple(
                        item.rr_achieved
                        for item in mature
                        if item.rr_achieved is not None
                    )
                ),
                average_mfe_percent=_mean(
                    tuple(
                        item.mfe_percent
                        for item in mature
                        if item.mfe_percent is not None
                    )
                ),
                average_mae_percent=_mean(
                    tuple(
                        item.mae_percent
                        for item in mature
                        if item.mae_percent is not None
                    )
                ),
                assignment_dimensions=(
                    "geometry|volatility|liquidity|trend|breakout_volume"
                ),
            )
        )
    return tuple(sorted(rows, key=lambda item: (-item.opportunities, item.cluster_id)))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["assign_natural_cluster", "cluster_summaries"]
