from datetime import UTC, datetime
from uuid import uuid4

from alpha.execution.enums import OrderType, TimeInForce
from alpha.execution.execution_engine import ExecutionEngine
from alpha.execution.order import Order
from alpha.execution.order_book import OrderBook
from alpha.portfolio.enums import Direction
from alpha.portfolio.portfolio_manager import PortfolioManager


def test_execution_updates_portfolio():
    engine = ExecutionEngine(OrderBook())
    portfolio = PortfolioManager()

    order = Order(
        order_id=uuid4(),
        symbol="RELIANCE",
        direction=Direction.LONG,
        quantity=10,
        timestamp=datetime.now(UTC),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )

    result = engine.submit(order)

    portfolio.apply_execution_result(result)

    assert len(portfolio._positions) == 1
