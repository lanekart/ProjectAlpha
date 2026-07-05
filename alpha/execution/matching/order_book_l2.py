from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from alpha.execution.order import Order


@dataclass
class OrderBookL2:
    """
    Level 2 order book with FIFO queues per price level.
    """

    bids: dict[Decimal, deque[Order]] = field(default_factory=dict)
    asks: dict[Decimal, deque[Order]] = field(default_factory=dict)

    def add_order(self, order: Order) -> None:
        if order.price is None:
            raise ValueError("Limit orders require price for L2 book")

        book = self.bids if order.direction == "BUY" else self.asks

        if order.price not in book:
            book[order.price] = deque()

        book[order.price].append(order)

    def best_bid(self) -> Decimal | None:
        return max(self.bids.keys(), default=None)

    def best_ask(self) -> Decimal | None:
        return min(self.asks.keys(), default=None)
