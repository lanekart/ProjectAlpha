"""Execution order book."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from alpha.execution.enums import OrderStatus
from alpha.execution.fill import Fill
from alpha.execution.order import Order


@dataclass(slots=True)
class OrderBook:
    """
    Lightweight in-memory order registry.

    Responsibilities:
      - Register orders
      - Prevent duplicate order IDs
      - Track fills
      - Track order status
    """

    _orders: dict[UUID, Order] = field(default_factory=dict)
    _fills: dict[UUID, list[Fill]] = field(default_factory=dict)
    _status: dict[UUID, OrderStatus] = field(default_factory=dict)

    def register(self, order: Order) -> None:
        """Register a newly submitted order."""

        if order.order_id in self._orders:
            raise ValueError(f"Duplicate order: {order.order_id}")

        self._orders[order.order_id] = order
        self._fills[order.order_id] = []
        self._status[order.order_id] = OrderStatus.PENDING

    def add_fill(self, fill: Fill) -> None:
        """Record a fill for an existing order."""

        if fill.order_id not in self._orders:
            raise ValueError(f"Unknown order: {fill.order_id}")

        self._fills[fill.order_id].append(fill)

        order = self._orders[fill.order_id]

        filled_qty = sum(f.quantity for f in self._fills[fill.order_id])

        if filled_qty >= order.quantity:
            self._status[fill.order_id] = OrderStatus.FILLED
        elif filled_qty > 0:
            self._status[fill.order_id] = OrderStatus.PARTIALLY_FILLED

    def get_status(self, order_id: UUID) -> OrderStatus:
        """Return the current status of an order."""

        return self._status.get(order_id, OrderStatus.REJECTED)

    def get_fills(self, order_id: UUID) -> list[Fill]:
        """Return all fills for an order."""

        return list(self._fills.get(order_id, []))

    def is_filled(self, order_id: UUID) -> bool:
        """True if the order is fully filled."""

        return self.get_status(order_id) == OrderStatus.FILLED

    def has_order(self, order_id: UUID) -> bool:
        """True if the order exists."""

        return order_id in self._orders

    def get_order(self, order_id: UUID) -> Order:
        """Retrieve a registered order."""

        return self._orders[order_id]
