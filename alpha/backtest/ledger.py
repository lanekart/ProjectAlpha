from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.backtest.models import BacktestTrade


@dataclass(frozen=True, slots=True)
class LedgerState:
    cash: Decimal
    positions: dict[str, int]
    trades: tuple[BacktestTrade, ...]

    @property
    def trade_count(self) -> int:
        return len(self.trades)


class ExecutionLedger:
    def apply(
        self,
        *,
        starting_cash: Decimal,
        trades: tuple[BacktestTrade, ...],
    ) -> LedgerState:
        if starting_cash < Decimal("0"):
            raise ValueError("starting_cash cannot be negative")

        cash = starting_cash
        positions: dict[str, int] = {}
        applied_trades: list[BacktestTrade] = []

        for trade in trades:
            if trade.quantity > 0:
                if trade.notional > cash:
                    raise ValueError("insufficient cash")

                cash -= trade.notional
                current_quantity = positions.get(trade.symbol, 0)
                positions[trade.symbol] = current_quantity + trade.quantity

            elif trade.quantity < 0:
                current_quantity = positions.get(trade.symbol, 0)
                sell_quantity = abs(trade.quantity)

                if sell_quantity > current_quantity:
                    raise ValueError("cannot sell more than current position")

                cash += trade.notional
                positions[trade.symbol] = current_quantity - sell_quantity

                if positions[trade.symbol] == 0:
                    del positions[trade.symbol]
            else:
                continue

            applied_trades.append(trade)

        return LedgerState(
            cash=cash,
            positions=positions,
            trades=tuple(applied_trades),
        )
