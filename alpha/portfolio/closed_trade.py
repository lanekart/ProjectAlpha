"""Immutable record of a completed trade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """
    Represents a fully completed trade.

    A ClosedTrade is produced after entry and exit fills have
    been successfully matched by the portfolio accounting engine.

    Once created, it is immutable and becomes part of the
    permanent trading history.
    """

    trade_id: UUID

    symbol: str

    entry_time: datetime
    exit_time: datetime

    entry_price: Decimal
    exit_price: Decimal

    quantity: int

    realized_pnl: Decimal

    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    strategy_id: str | None = None

    @property
    def gross_value(self) -> Decimal:
        """Gross value of the trade at entry."""
        return self.entry_price * Decimal(self.quantity)

    @property
    def net_pnl(self) -> Decimal:
        """Realized PnL after costs."""
        return self.realized_pnl - self.commission - self.slippage
