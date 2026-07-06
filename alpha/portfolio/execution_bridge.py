from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from alpha.execution.enums import Direction, OrderType, TimeInForce
from alpha.execution.order import Order
from alpha.portfolio.order_intent import OrderIntent, OrderSide


@dataclass(slots=True)
class ExecutionBridge:
    """
    Converts portfolio-level OrderIntent into execution-layer Orders.

    This is a strict boundary translator:
    - no strategy logic
    - no sizing logic
    - no risk logic (assumed already applied upstream)
    """

    default_tif: TimeInForce = TimeInForce.DAY
    default_order_type: OrderType = OrderType.MARKET

    def translate(self, intents: Sequence[OrderIntent]) -> tuple[Order, ...]:
        orders: list[Order] = []

        for intent in intents:
            orders.append(self._to_order(intent))

        return tuple(orders)

    def _to_order(self, intent: OrderIntent) -> Order:
        return Order(
            symbol=intent.symbol,
            direction=self._map_side(intent.side),
            quantity=intent.quantity,
            order_type=self.default_order_type,
            time_in_force=self.default_tif,
        )

    def _map_side(self, side: OrderSide) -> Direction:
        if side == OrderSide.BUY:
            return Direction.LONG
        return Direction.SHORT
