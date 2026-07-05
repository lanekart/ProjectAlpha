from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """
    Immutable accounting event.

    Every portfolio state transition is represented by one LedgerEvent.

    Ledger events form the permanent audit trail for the portfolio.
    """

    event_id: UUID

    fill_id: UUID
    order_id: UUID

    symbol: str

    quantity: int
    price: Decimal

    realized_pnl: Decimal

    position_quantity: int
    average_price: Decimal

    timestamp: datetime

    def __post_init__(self) -> None:
        if self.price <= Decimal("0"):
            raise ValueError("price must be positive")

        if self.average_price < Decimal("0"):
            raise ValueError("average_price cannot be negative")
