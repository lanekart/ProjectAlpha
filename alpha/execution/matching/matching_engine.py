from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from alpha.execution.fill import Fill
from alpha.execution.matching.enums import MatchType
from alpha.execution.matching.match_result import MatchResult
from alpha.execution.matching.order_book_l2 import OrderBookL2
from alpha.execution.order import Order


@dataclass
class MatchingEngine:
    """
    Deterministic price-time priority matching engine.
    """

    book: OrderBookL2

    def match(self, order: Order, market_price: Decimal) -> MatchResult:
        fills: list[Fill] = []

        # MARKET ORDER → immediate fill
        if order.order_type == "MARKET":
            fills.append(
                Fill(
                    fill_id=order.order_id,
                    order_id=order.order_id,
                    quantity=order.quantity,
                    price=market_price,
                    timestamp=datetime.now(UTC),
                    commission=Decimal("0"),
                    slippage=Decimal("0"),
                )
            )
            return MatchResult(match_type=MatchType.FULL, fills=tuple(fills))

        # LIMIT ORDER → rest in book
        self.book.add_order(order)

        return MatchResult(match_type=MatchType.NONE, fills=())
