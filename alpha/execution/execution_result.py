"""Execution result model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.execution.fill import Fill


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Result returned by the ExecutionEngine after attempting
    to execute an order.
    """

    accepted: bool
    fills: tuple[Fill, ...] = ()
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.accepted:
            if self.rejection_reason is not None:
                raise ValueError("Accepted execution cannot have a rejection reason.")
        else:
            if self.rejection_reason is None:
                raise ValueError("Rejected execution must include a rejection reason.")

            if self.fills:
                raise ValueError("Rejected execution cannot contain fills.")

    @property
    def total_quantity(self) -> int:
        """Total executed quantity."""
        return sum(fill.quantity for fill in self.fills)

    @property
    def total_value(self) -> Decimal:
        """Gross execution value."""
        return sum(
            (fill.price * Decimal(fill.quantity) for fill in self.fills),
            Decimal("0"),
        )

    @property
    def average_price(self) -> Decimal:
        """Volume weighted average execution price."""

        if not self.fills:
            return Decimal("0")

        qty = self.total_quantity

        if qty == 0:
            return Decimal("0")

        return self.total_value / Decimal(qty)

    @property
    def commission(self) -> Decimal:
        return sum(
            (fill.commission for fill in self.fills),
            Decimal("0"),
        )

    @property
    def slippage(self) -> Decimal:
        return sum(
            (fill.slippage for fill in self.fills),
            Decimal("0"),
        )
