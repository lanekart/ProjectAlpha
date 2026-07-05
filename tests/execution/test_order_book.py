from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.execution.enums import OrderStatus, OrderType, TimeInForce
from alpha.execution.fill import Fill
from alpha.execution.order import Order
from alpha.execution.order_book import OrderBook
from alpha.portfolio.enums import Direction


def make_order():
    return Order(
        order_id=uuid4(),
        symbol="RELIANCE",
        direction=Direction.LONG,
        quantity=10,
        timestamp=datetime.now(UTC),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )


def test_register_order():
    ob = OrderBook()
    order = make_order()

    ob.register(order)

    assert ob.get_status(order.order_id) == OrderStatus.PENDING


def test_duplicate_order_rejected():
    ob = OrderBook()
    order = make_order()

    ob.register(order)

    try:
        ob.register(order)
        assert False
    except ValueError:
        assert True


def test_fill_updates_status():
    ob = OrderBook()
    order = make_order()

    ob.register(order)

    fill = Fill(
        fill_id=uuid4(),
        order_id=order.order_id,
        quantity=10,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )

    ob.add_fill(fill)

    assert ob.get_status(order.order_id) == OrderStatus.FILLED


def test_partial_fill():
    ob = OrderBook()
    order = make_order()

    ob.register(order)

    fill = Fill(
        fill_id=uuid4(),
        order_id=order.order_id,
        quantity=5,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )

    ob.add_fill(fill)

    assert ob.get_status(order.order_id) == OrderStatus.PARTIALLY_FILLED


def test_get_fills():
    ob = OrderBook()
    order = make_order()

    ob.register(order)

    fill = Fill(
        fill_id=uuid4(),
        order_id=order.order_id,
        quantity=10,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )

    ob.add_fill(fill)

    fills = ob.get_fills(order.order_id)

    assert len(fills) == 1
