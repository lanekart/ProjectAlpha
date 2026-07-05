from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from alpha.execution.fill import Fill


@dataclass
class MatchedTrade:
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    realized_pnl: Decimal


@dataclass
class MatchingEngine:
    """
    Matches entry and exit fills into real trades.

    G20: institutional-grade trade reconstruction.
    """

    open_positions: list[Fill] = field(default_factory=list)
    closed_trades: list[MatchedTrade] = field(default_factory=list)

    def process_fill(self, fill: Fill) -> None:
        qty = fill.quantity

        if qty > 0:
            self.open_positions.append(fill)
            return

        remaining = abs(qty)

        while remaining > 0 and self.open_positions:
            entry = self.open_positions.pop(0)

            matched_qty = min(entry.quantity, remaining)

            pnl = (fill.price - entry.price) * Decimal(matched_qty)

            self.closed_trades.append(
                MatchedTrade(
                    entry_price=entry.price,
                    exit_price=fill.price,
                    quantity=matched_qty,
                    realized_pnl=pnl,
                )
            )

            remaining_qty = entry.quantity - matched_qty
            remaining -= matched_qty

            if remaining_qty > 0:
                self.open_positions.insert(
                    0,
                    replace(entry, quantity=remaining_qty),
                )
