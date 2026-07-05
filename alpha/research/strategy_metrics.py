from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StrategyMetrics:
    """
    Raw performance signals for a strategy.
    """

    total_trades: int = 0
    winning_trades: int = 0

    total_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")

    total_cost: Decimal = Decimal("0")

    def win_rate(self) -> Decimal:
        if self.total_trades == 0:
            return Decimal("0")

        return Decimal(self.winning_trades) / Decimal(self.total_trades)
