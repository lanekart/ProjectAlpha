from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.portfolio.allocation.rebalance import RebalancePlanner
from alpha.portfolio.allocation.target import AllocationTarget, PortfolioAllocation
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot


def make_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("10000"),
        positions=(
            PositionSnapshot(
                symbol="RELIANCE",
                quantity=10,
                average_price=Decimal("2500"),
            ),
        ),
    )


def test_rebalance_planner_creates_buy_order() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(AllocationTarget("RELIANCE", Decimal("0.75")),)
    )

    plan = RebalancePlanner().plan(
        snapshot=snapshot,
        allocation=allocation,
        prices={"RELIANCE": Decimal("2500")},
    )

    order = plan.orders[0]

    assert order.symbol == "RELIANCE"
    assert order.current_quantity == 10
    assert order.target_quantity == 10
    assert order.delta_quantity == 0
    assert order.is_noop
    assert order.notional == Decimal("0")


def test_rebalance_planner_creates_sell_order() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(AllocationTarget("RELIANCE", Decimal("0.25")),)
    )

    plan = RebalancePlanner().plan(
        snapshot=snapshot,
        allocation=allocation,
        prices={"RELIANCE": Decimal("2500")},
    )

    order = plan.orders[0]

    assert order.current_quantity == 10
    assert order.target_quantity == 3
    assert order.delta_quantity == -7
    assert order.is_sell
    assert order.notional == Decimal("17500")


def test_rebalance_planner_creates_new_position_buy() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(AllocationTarget("TCS", Decimal("0.50")),)
    )

    plan = RebalancePlanner().plan(
        snapshot=snapshot,
        allocation=allocation,
        prices={"TCS": Decimal("4000")},
    )

    order = plan.orders[0]

    assert order.symbol == "TCS"
    assert order.current_quantity == 0
    assert order.target_quantity == 4
    assert order.delta_quantity == 4
    assert order.is_buy
    assert order.notional == Decimal("16000")


def test_rebalance_plan_aggregates_orders() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(
            AllocationTarget("RELIANCE", Decimal("0.25")),
            AllocationTarget("TCS", Decimal("0.50")),
        )
    )

    plan = RebalancePlanner().plan(
        snapshot=snapshot,
        allocation=allocation,
        prices={
            "RELIANCE": Decimal("2500"),
            "TCS": Decimal("4000"),
        },
    )

    assert len(plan.orders) == 2
    assert len(plan.buy_orders) == 1
    assert len(plan.sell_orders) == 1
    assert plan.total_buy_notional == Decimal("16000")
    assert plan.total_sell_notional == Decimal("17500")


def test_rebalance_planner_rejects_missing_price() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(AllocationTarget("RELIANCE", Decimal("0.25")),)
    )

    with pytest.raises(ValueError):
        RebalancePlanner().plan(
            snapshot=snapshot,
            allocation=allocation,
            prices={},
        )


def test_rebalance_planner_rejects_invalid_price() -> None:
    snapshot = make_snapshot()

    allocation = PortfolioAllocation(
        targets=(AllocationTarget("RELIANCE", Decimal("0.25")),)
    )

    with pytest.raises(ValueError):
        RebalancePlanner().plan(
            snapshot=snapshot,
            allocation=allocation,
            prices={"RELIANCE": Decimal("0")},
        )
