from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.backtest.engine import BacktestEngine
from alpha.backtest.models import BacktestOrder, BacktestResult
from alpha.backtest.rebalance_adapter import RebalanceExecutionAdapter
from alpha.portfolio.allocation.optimization_planner import (
    OptimizedRebalancePlan,
    OptimizedRebalancePlanner,
)
from alpha.portfolio.optimizer import OptimizationInput
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class OptimizedBacktestResult:
    """
    Full result of an optimized rebalance backtest run.
    """

    optimized_rebalance_plan: OptimizedRebalancePlan
    orders: tuple[BacktestOrder, ...]
    backtest_result: BacktestResult


@dataclass(frozen=True, slots=True)
class OptimizedBacktestRunner:
    """
    Coordinates optimization, rebalance planning, order adaptation, and backtesting.

    BacktestEngine remains order-driven and has no dependency on optimizers,
    allocations, or rebalance planning.
    """

    optimized_rebalance_planner: OptimizedRebalancePlanner = field(
        default_factory=OptimizedRebalancePlanner
    )
    execution_adapter: RebalanceExecutionAdapter = field(
        default_factory=RebalanceExecutionAdapter
    )
    backtest_engine: BacktestEngine = field(default_factory=BacktestEngine)

    def run(
        self,
        *,
        config: OptimizerConfig,
        optimization_input: OptimizationInput,
        snapshot: PortfolioSnapshot,
        prices: dict[str, Decimal],
    ) -> OptimizedBacktestResult:
        optimized_rebalance_plan = self.optimized_rebalance_planner.plan(
            config=config,
            optimization_input=optimization_input,
            snapshot=snapshot,
            prices=prices,
        )
        orders = self.execution_adapter.to_orders(
            optimized_rebalance_plan.rebalance_plan
        )
        backtest_result = self.backtest_engine.run(
            starting_cash=snapshot.cash,
            orders=orders,
            prices=prices,
        )

        return OptimizedBacktestResult(
            optimized_rebalance_plan=optimized_rebalance_plan,
            orders=orders,
            backtest_result=backtest_result,
        )
