from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

from alpha.execution.exit.exit_policy import ExitPolicy
from alpha.execution.exit.signals import ExitReason, ExitSignal


class StopLossPolicy(ExitPolicy):
    """
    Exits position when loss exceeds threshold.
    """

    def __init__(self, stop_loss_pct: Decimal):
        self.stop_loss_pct = stop_loss_pct

    def evaluate(
        self,
        context: Mapping[str, Any],
    ) -> list[ExitSignal]:
        signals: list[ExitSignal] = []

        positions = context.get("positions", {})
        prices = context.get("prices", {})

        for position_id, position in positions.items():
            symbol = position["symbol"]
            entry_price = position["avg_price"]
            quantity = position["quantity"]

            current_price = prices.get(symbol)
            if current_price is None:
                continue

            pnl_pct = ((current_price - entry_price) / entry_price) * Decimal("100")

            if pnl_pct <= -self.stop_loss_pct:
                signals.append(
                    ExitSignal(
                        position_id=UUID(position_id),
                        symbol=symbol,
                        quantity=quantity,
                        reason=ExitReason.STOP_LOSS,
                    )
                )

        return signals
