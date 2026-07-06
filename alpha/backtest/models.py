from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BacktestOrder:
    symbol: str
    quantity: int


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    symbol: str
    quantity: int
    price: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    starting_cash: Decimal
    ending_cash: Decimal
    equity: Decimal
    positions: dict[str, int]
    trades: tuple[BacktestTrade, ...]

    @property
    def trade_count(self) -> int:
        return len(self.trades)
