from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alpha.execution.enums import Direction, OrderType, TimeInForce


@dataclass(slots=True)
class Order:
    """
    Trading order.
    """

    order_id: UUID = field(default_factory=uuid4)

    symbol: str = ""
    direction: Direction = Direction.LONG

    quantity: int = 0
    timestamp: datetime | None = None

    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY

    price: Decimal | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")

        if self.order_type == OrderType.MARKET:
            if self.price is not None:
                raise ValueError("market orders cannot specify a price")

        if self.order_type == OrderType.LIMIT:
            if self.price is None:
                raise ValueError("limit orders require a price")

            if self.price <= Decimal("0"):
                raise ValueError("price must be positive")

    @property
    def is_market(self) -> bool:
        return self.order_type == OrderType.MARKET

    @property
    def is_limit(self) -> bool:
        return self.order_type == OrderType.LIMIT
