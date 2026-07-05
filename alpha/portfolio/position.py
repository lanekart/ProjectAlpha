from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from alpha.portfolio.enums import ExitReason, PositionStatus


@dataclass
class Position:
    """
    Canonical portfolio position model.

    Supports:
    - Long and short positions
    - Entry/exit bookkeeping
    - Realized/unrealized PnL
    - Position lifecycle state
    """

    symbol: str

    quantity: int = 0

    entry_price: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")

    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    entry_time: datetime | None = None
    exit_date: date | None = None

    exit_price: Decimal | None = None
    exit_reason: ExitReason | None = None

    status: PositionStatus = PositionStatus.OPEN

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0
