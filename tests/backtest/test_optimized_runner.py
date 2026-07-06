from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.backtest import OptimizedBacktestRunner
from alpha.portfolio import OptimizationInput, OptimizerConfig
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


def test_optimized_backtest_runner_executes_full_pipeline() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("100000"),
    )

    result = OptimizedBacktestRunner().run(
        config=OptimizerConfig(name="equal_weight"),
        optimization_input=OptimizationInput(
            universe=("RELIANCE", "TCS"),
        ),
        snapshot=snapshot,
        prices={
            "RELIANCE": Decimal("2500"),
            "TCS": Decimal("5000"),
        },
    )

    assert tuple(order.symbol for order in result.orders) == ("RELIANCE", "TCS")
    assert tuple(order.quantity for order in result.orders) == (20, 10)
    assert result.backtest_result.ending_cash == Decimal("0")
    assert result.backtest_result.positions == {
        "RELIANCE": 20,
        "TCS": 10,
    }
    assert result.backtest_result.equity == Decimal("100000")


def test_optimized_backtest_runner_preserves_optimization_result() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("100000"),
    )

    result = OptimizedBacktestRunner().run(
        config=OptimizerConfig(name="equal_weight"),
        optimization_input=OptimizationInput(
            universe=("RELIANCE", "TCS"),
        ),
        snapshot=snapshot,
        prices={
            "RELIANCE": Decimal("2500"),
            "TCS": Decimal("5000"),
        },
    )

    optimization_result = result.optimized_rebalance_plan.optimization_result

    assert optimization_result.success
    assert optimization_result.target_weights["RELIANCE"] == Decimal("0.5")
    assert optimization_result.target_weights["TCS"] == Decimal("0.5")


def test_optimized_backtest_runner_preserves_rebalance_plan() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("100000"),
    )

    result = OptimizedBacktestRunner().run(
        config=OptimizerConfig(name="equal_weight"),
        optimization_input=OptimizationInput(
            universe=("RELIANCE", "TCS"),
        ),
        snapshot=snapshot,
        prices={
            "RELIANCE": Decimal("2500"),
            "TCS": Decimal("5000"),
        },
    )

    rebalance_plan = result.optimized_rebalance_plan.rebalance_plan

    assert len(rebalance_plan.orders) == 2
    assert rebalance_plan.total_buy_notional == Decimal("100000")
