"""Execution fill model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Fill:
    """
    Represents a single execution (fill) of an order.

    An order may produce one or many fills.
    """

    fill_id: UUID
    order_id: UUID

    quantity: int
    price: Decimal
    timestamp: datetime

    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("fill quantity must be > 0")

        if self.price <= Decimal("0"):
            raise ValueError("fill price must be > 0")

        if self.commission < Decimal("0"):
            raise ValueError("commission cannot be negative")

        if self.slippage < Decimal("0"):
            raise ValueError("slippage cannot be negative")

    @property
    def gross_value(self) -> Decimal:
        """Execution value before costs."""
        return self.price * Decimal(self.quantity)

    @property
    def total_cost(self) -> Decimal:
        """Total execution costs."""
        return self.commission + self.slippage

    @property
    def net_value(self) -> Decimal:
        """Execution value including costs."""
        return self.gross_value + self.total_cost
