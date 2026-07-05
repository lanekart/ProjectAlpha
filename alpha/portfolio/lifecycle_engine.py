from __future__ import annotations

from dataclasses import dataclass

from alpha.execution.enums import Direction, OrderType, TimeInForce
from alpha.execution.exit.signals import ExitSignal
from alpha.execution.order import Order


@dataclass
class PortfolioLifecycleEngine:
    """
    Converts ExitSignals → Orders.

    This is the bridge between:
    Exit logic → Execution system
    """

    def generate_orders(self, signals: list[ExitSignal]) -> list[Order]:
        orders: list[Order] = []

        for signal in signals:
            orders.append(
                Order(
                    symbol=signal.symbol,
                    direction=self._reverse_direction(signal),
                    quantity=signal.quantity,
                    timestamp=None,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                )
            )

        return orders

    def _reverse_direction(self, signal: ExitSignal) -> Direction:
        """
        Return the opposite trading direction.

        G15 simplification:
        Exit orders always use SHORT until position-side tracking
        is introduced in a later generation.
        """

        return Direction.SHORT
