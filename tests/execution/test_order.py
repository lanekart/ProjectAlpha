from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.execution.enums import OrderType, TimeInForce
from alpha.execution.order import Order
from alpha.portfolio.enums import Direction


def test_market_order_valid():
    order = Order(
        order_id=uuid4(),
        symbol="RELIANCE",
        direction=Direction.LONG,
        quantity=10,
        timestamp=datetime.now(UTC),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )

    assert order.is_market


def test_limit_order_requires_price():
    with pytest.raises(ValueError):
        Order(
            order_id=uuid4(),
            symbol="RELIANCE",
            direction=Direction.LONG,
            quantity=10,
            timestamp=datetime.now(UTC),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
        )


def test_invalid_quantity():
    with pytest.raises(ValueError):
        Order(
            order_id=uuid4(),
            symbol="RELIANCE",
            direction=Direction.LONG,
            quantity=0,
            timestamp=datetime.now(UTC),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )


def test_market_order_cannot_have_price():
    with pytest.raises(ValueError):
        Order(
            order_id=uuid4(),
            symbol="RELIANCE",
            direction=Direction.LONG,
            quantity=10,
            timestamp=datetime.now(UTC),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            price=Decimal("100"),
        )
