from __future__ import annotations

from decimal import Decimal

from alpha.strategy_lab.models import LabStrategyResult, LeaderboardView


class StrategyLeaderboard:
    """Create transparent ranking views without hiding underlying metrics."""

    def rank(
        self,
        results: tuple[LabStrategyResult, ...],
        *,
        view: LeaderboardView = LeaderboardView.COMPOSITE,
        top: int | None = None,
    ) -> tuple[LabStrategyResult, ...]:
        ordered = tuple(
            sorted(results, key=lambda item: _key(item, view), reverse=True)
        )
        return ordered if top is None else ordered[: max(0, top)]


def _key(item: LabStrategyResult, view: LeaderboardView) -> tuple[Decimal, int, str]:
    metrics = item.metrics
    value = {
        LeaderboardView.COMPOSITE: item.research_score,
        LeaderboardView.EXPECTANCY: metrics.expectancy_pct,
        LeaderboardView.PRECISION: metrics.precision_pct,
        LeaderboardView.PROFIT_FACTOR: metrics.profit_factor,
        LeaderboardView.PAYOFF: metrics.payoff_ratio,
        LeaderboardView.DRAWDOWN: (
            None
            if metrics.maximum_drawdown_pct is None
            else Decimal("100") - metrics.maximum_drawdown_pct
        ),
        LeaderboardView.RISK_ADJUSTED: metrics.sortino_ratio or metrics.sharpe_ratio,
        LeaderboardView.CAPITAL_UTILISATION: metrics.capital_utilisation_pct,
        LeaderboardView.STABILITY: metrics.positive_period_pct,
    }[view]
    return (
        Decimal("-999999") if value is None else value,
        metrics.completed_trades,
        item.strategy.strategy_id,
    )


__all__ = ["StrategyLeaderboard"]
