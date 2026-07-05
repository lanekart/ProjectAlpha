from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from alpha.portfolio.inventory import InventoryLot


@dataclass(slots=True)
class InventoryBook:
    """
    FIFO inventory ledger.

    Stores open acquisition lots and consumes them
    strictly in FIFO order.
    """

    _lots: deque[InventoryLot] = field(default_factory=deque)

    def add_lot(self, lot: InventoryLot) -> None:
        self._lots.append(lot)

    def open_lots(self) -> tuple[InventoryLot, ...]:
        return tuple(self._lots)

    def remaining_quantity(self) -> int:
        return sum(lot.quantity for lot in self._lots)

    def cost_basis(self) -> Decimal:
        qty = self.remaining_quantity()

        if qty == 0:
            return Decimal("0")

        total = sum(lot.price * lot.quantity for lot in self._lots)

        return total / Decimal(qty)

    def consume_fifo(
        self,
        quantity: int,
        exit_price: Decimal,
    ) -> Decimal:
        """
        Consume inventory using FIFO.

        Returns realized PnL.
        """

        if quantity <= 0:
            raise ValueError("quantity must be positive")

        remaining = quantity
        realized = Decimal("0")

        while remaining > 0:
            if not self._lots:
                raise ValueError("insufficient inventory")

            lot = self._lots[0]

            matched = min(lot.quantity, remaining)

            realized += (exit_price - lot.price) * Decimal(matched)

            lot.quantity -= matched
            remaining -= matched

            if lot.is_empty:
                self._lots.popleft()

        return realized
