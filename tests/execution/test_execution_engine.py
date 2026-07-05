from decimal import Decimal

from alpha.execution.enums import OrderType, TimeInForce
from alpha.execution.execution_engine import ExecutionEngine
from alpha.execution.order import Order
from alpha.execution.order_book import OrderBook
from alpha.portfolio.enums import Direction


def make_market_order():
    return Order(
        order_id=None,  # irrelevant for test uniqueness logic
        symbol="RELIANCE",
        direction=Direction.LONG,
        quantity=10,
        timestamp=None,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )


def make_limit_order(price: Decimal):
    return Order(
        order_id=None,
        symbol="RELIANCE",
        direction=Direction.LONG,
        quantity=10,
        timestamp=None,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        price=price,
    )


def test_market_execution():
    engine = ExecutionEngine(OrderBook())
    order = make_market_order()

    result = engine.submit(order)

    assert result.accepted

    # G13 CHANGE: allow partial fills
    assert len(result.fills) >= 1

    total_qty = sum(f.quantity for f in result.fills)
    assert total_qty == order.quantity


def test_limit_executable():
    engine = ExecutionEngine(OrderBook())

    order = make_limit_order(Decimal("150"))

    result = engine.submit(order)

    assert result.accepted

    # G13 CHANGE: allow multiple fills
    assert len(result.fills) >= 1

    total_qty = sum(f.quantity for f in result.fills)
    assert total_qty == order.quantity


def test_limit_rejected():
    engine = ExecutionEngine(OrderBook())

    order = make_limit_order(Decimal("10"))

    result = engine.submit(order)

    assert not result.accepted
    assert result.rejection_reason is not None


def test_order_registered_in_book():
    engine = ExecutionEngine(OrderBook())

    order = make_market_order()

    engine.submit(order)

    assert len(engine._order_book._orders) > 0
