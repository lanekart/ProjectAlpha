"""Represents an open portfolio position."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True)
class Position:
    """
    Represents an open position.

    A Position is mutable because additional fills may increase,
    decrease or completely close the exposure.
    """

    position_id: UUID

    symbol: str

    quantity: int

    average_price: Decimal

    entry_time: datetime

    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    strategy_id: str | None = None

    @property
    def market_value(self) -> Decimal:
        return self.average_price * Decimal(abs(self.quantity))

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0
