from decimal import Decimal

from alpha.backtest import BacktestOrder, RebalanceExecutionAdapter
from alpha.portfolio.allocation import RebalanceOrder, RebalancePlan


def test_rebalance_execution_adapter_converts_plan_to_backtest_orders() -> None:
    plan = RebalancePlan(
        orders=(
            RebalanceOrder(
                symbol="RELIANCE",
                target_weight=Decimal("0.60"),
                current_quantity=0,
                target_quantity=10,
                delta_quantity=10,
                price=Decimal("2500"),
            ),
            RebalanceOrder(
                symbol="TCS",
                target_weight=Decimal("0.40"),
                current_quantity=8,
                target_quantity=5,
                delta_quantity=-3,
                price=Decimal("4000"),
            ),
        )
    )

    orders = RebalanceExecutionAdapter().to_orders(plan)

    assert orders == (
        BacktestOrder(symbol="RELIANCE", quantity=10),
        BacktestOrder(symbol="TCS", quantity=-3),
    )


def test_rebalance_execution_adapter_excludes_noop_orders_by_default() -> None:
    plan = RebalancePlan(
        orders=(
            RebalanceOrder(
                symbol="RELIANCE",
                target_weight=Decimal("1"),
                current_quantity=10,
                target_quantity=10,
                delta_quantity=0,
                price=Decimal("2500"),
            ),
        )
    )

    orders = RebalanceExecutionAdapter().to_orders(plan)

    assert orders == ()


def test_rebalance_execution_adapter_can_include_noop_orders() -> None:
    plan = RebalancePlan(
        orders=(
            RebalanceOrder(
                symbol="RELIANCE",
                target_weight=Decimal("1"),
                current_quantity=10,
                target_quantity=10,
                delta_quantity=0,
                price=Decimal("2500"),
            ),
        )
    )

    orders = RebalanceExecutionAdapter(include_noop_orders=True).to_orders(plan)

    assert orders == (BacktestOrder(symbol="RELIANCE", quantity=0),)


def test_rebalance_execution_adapter_preserves_order_sequence() -> None:
    plan = RebalancePlan(
        orders=(
            RebalanceOrder(
                symbol="A",
                target_weight=Decimal("0.50"),
                current_quantity=0,
                target_quantity=1,
                delta_quantity=1,
                price=Decimal("100"),
            ),
            RebalanceOrder(
                symbol="B",
                target_weight=Decimal("0.50"),
                current_quantity=0,
                target_quantity=2,
                delta_quantity=2,
                price=Decimal("100"),
            ),
        )
    )

    orders = RebalanceExecutionAdapter().to_orders(plan)

    assert tuple(order.symbol for order in orders) == ("A", "B")
