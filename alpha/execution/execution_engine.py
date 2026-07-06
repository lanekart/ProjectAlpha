from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from alpha.execution.enums import OrderType
from alpha.execution.execution_result import ExecutionResult
from alpha.execution.fill import Fill
from alpha.execution.order import Order
from alpha.execution.order_book import OrderBook


@dataclass(slots=False)
class ExecutionEngine:
    """
    Executes validated orders against the current market context.

    Phase G21.3:
    - deterministic execution model
    - full-fill simulation
    - symbol-aware fills
    - typed execution pipeline
    """

    order_book: OrderBook

    # Backwards compatibility for older tests.
    _order_book: OrderBook = field(init=False, repr=False)

    DEFAULT_MARKET_PRICE = Decimal("100")

    def __post_init__(self) -> None:
        self._order_book = self.order_book

    def submit(
        self,
        order: Order,
        market_context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        market_context = market_context or {}

        self.order_book.register(order)

        if not self._is_executable(order, market_context):
            return ExecutionResult(
                accepted=False,
                fills=(),
                rejection_reason="Order not executable under current market conditions",
            )

        fills = tuple(self._execute(order, market_context))

        return ExecutionResult(
            accepted=True,
            fills=fills,
        )

    def _is_executable(
        self,
        order: Order,
        market_context: dict[str, Any],
    ) -> bool:
        if order.order_type is OrderType.MARKET:
            return True

        if order.order_type is OrderType.LIMIT:
            if order.price is None:
                return False

            market_price = Decimal(
                market_context.get(
                    "price",
                    self.DEFAULT_MARKET_PRICE,
                )
            )

            return market_price <= order.price

        return False

    def _execute(
        self,
        order: Order,
        market_context: dict[str, Any],
    ) -> list[Fill]:
        price = Decimal(
            market_context.get(
                "price",
                order.price if order.price is not None else self.DEFAULT_MARKET_PRICE,
            )
        )

        fill = Fill(
            fill_id=uuid4(),
            order_id=order.order_id,
            symbol=order.symbol,
            quantity=order.quantity,
            price=price,
            timestamp=order.timestamp or datetime.now(UTC),
        )

        self.order_book.add_fill(fill)

        return [fill]
