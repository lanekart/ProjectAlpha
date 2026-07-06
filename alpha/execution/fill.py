from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Fill:
    """
    Immutable execution fill.

    Invariants
    ----------
    - fill_id is immutable
    - order_id is immutable
    - symbol is non-empty
    - quantity > 0
    - price > 0
    - commission >= 0
    - slippage >= 0
    - timestamp is timezone-aware
    """

    fill_id: UUID
    order_id: UUID

    symbol: str

    quantity: int
    price: Decimal
    timestamp: datetime

    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")

        if self.quantity <= 0:
            raise ValueError("fill quantity must be > 0")

        if self.price <= Decimal("0"):
            raise ValueError("fill price must be > 0")

        if self.commission < Decimal("0"):
            raise ValueError("commission cannot be negative")

        if self.slippage < Decimal("0"):
            raise ValueError("slippage cannot be negative")

        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
