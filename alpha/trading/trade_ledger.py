from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.trading.trade import Trade


@dataclass
class TradeLedger:
    """
    Stores and manages all completed trade lifecycles.
    """

    _trades: dict[str, Trade] = field(default_factory=dict)

    def open_trade(self, trade: Trade) -> None:
        self._trades[str(trade.trade_id)] = trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: Decimal,
    ) -> None:

        trade = self._trades[trade_id]
        trade.exit_price = exit_price
        trade.is_open = False

        trade.realized_pnl = (exit_price - trade.entry_price) * trade.quantity

    def get_trade(self, trade_id: str) -> Trade:
        return self._trades[trade_id]
