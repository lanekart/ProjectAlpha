from __future__ import annotations

from decimal import Decimal

from alpha.execution.fill import Fill
from alpha.portfolio.position import Position


class AccountingEngine:
    """
    Handles true financial updates:

    - position netting
    - avg cost updates
    - realized PnL
    - cash impact (future extension)
    """

    def apply_fill(self, position: Position | None, fill: Fill) -> Position:
        if position is None:
            return Position(
                symbol=str(fill.order_id),
                quantity=fill.quantity,
                avg_price=fill.price,
                entry_time=fill.timestamp,
            )

        old_qty = position.quantity
        new_qty = old_qty + fill.quantity

        # if reversing position → realize PnL (simplified model)
        if old_qty != 0 and (old_qty > 0) != (new_qty > 0):
            position.realized_pnl += (fill.price - position.avg_price) * Decimal(
                old_qty
            )

        if new_qty != 0:
            position.avg_price = (
                (position.avg_price * abs(old_qty)) + (fill.price * fill.quantity)
            ) / abs(new_qty)

        position.quantity = new_qty

        if position.entry_time is None:
            position.entry_time = fill.timestamp

        return position
