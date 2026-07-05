from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class PositionState:
    quantity: int = 0
    avg_price: Decimal = Decimal("0")


@dataclass
class PositionTracker:
    """
    True net position tracking (post-matching system).
    """

    positions: dict[str, PositionState] = field(default_factory=dict)

    def apply_fill(self, symbol: str, price: Decimal, quantity: int) -> None:
        p = self.positions.get(symbol)

        if p is None:
            self.positions[symbol] = PositionState(quantity, price)
            return

        new_qty = p.quantity + quantity

        if new_qty != 0:
            p.avg_price = ((p.avg_price * abs(p.quantity)) + (price * quantity)) / abs(
                new_qty
            )

        p.quantity = new_qty
