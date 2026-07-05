from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.research.strategy_metrics import StrategyMetrics


@dataclass
class PerformanceTracker:
    """
    Tracks strategy performance over time.
    """

    _metrics: dict[str, StrategyMetrics] = field(default_factory=dict)

    def update_trade(
        self,
        strategy_id: str,
        pnl: Decimal,
        cost: Decimal,
        is_win: bool,
    ) -> None:
        m = self._metrics.get(strategy_id)

        if m is None:
            m = StrategyMetrics()
            self._metrics[strategy_id] = m

        m.total_trades += 1
        m.total_pnl += pnl
        m.total_cost += cost

        if is_win:
            m.winning_trades += 1

    def get_metrics(self, strategy_id: str) -> StrategyMetrics:
        return self._metrics[strategy_id]
