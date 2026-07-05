from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.research.strategy_metrics import StrategyMetrics


@dataclass
class AlphaScoreEngine:
    """
    Converts raw metrics into a single "strategy quality score".
    """

    def score(self, m: StrategyMetrics) -> Decimal:
        if m.total_trades == 0:
            return Decimal("0")

        win_rate = m.win_rate()

        pnl_factor = m.total_pnl / Decimal(m.total_trades)
        cost_penalty = m.total_cost / Decimal(m.total_trades)

        drawdown_penalty = m.max_drawdown

        score = (
            win_rate * Decimal("40")
            + pnl_factor * Decimal("30")
            - cost_penalty * Decimal("10")
            - drawdown_penalty * Decimal("20")
        )

        return max(score, Decimal("0"))
