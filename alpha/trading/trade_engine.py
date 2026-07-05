from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from alpha.trading.trade import Trade
from alpha.trading.trade_ledger import TradeLedger


class TradeEngine:
    """
    Converts fills into full trade lifecycle objects.
    """

    def __init__(self, ledger: TradeLedger):
        self._ledger = ledger

    def open_trade(
        self,
        symbol: str,
        price: Decimal,
        quantity: int,
    ) -> Trade:

        trade = Trade(
            trade_id=uuid4(),
            symbol=symbol,
            entry_price=price,
            quantity=quantity,
            is_open=True,
        )

        self._ledger.open_trade(trade)

        return trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: Decimal,
    ) -> None:

        self._ledger.close_trade(trade_id, exit_price)
