from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.portfolio.allocation.optimizer_adapter import OptimizationAllocationAdapter
from alpha.portfolio.allocation.rebalance import RebalancePlan, RebalancePlanner
from alpha.portfolio.allocation.target import PortfolioAllocation
from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.optimizer_factory import OptimizerFactory
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class OptimizedRebalancePlan:
    optimization_result: OptimizationResult
    allocation: PortfolioAllocation
    rebalance_plan: RebalancePlan


@dataclass(frozen=True, slots=True)
class OptimizedRebalancePlanner:
    """
    Composes optimizer construction, optimization output adaptation,
    and rebalance planning.

    This service deliberately stops before execution. Backtest execution remains
    order-driven and independent from optimizer/allocation concerns.
    """

    optimizer_factory: OptimizerFactory = field(default_factory=OptimizerFactory)
    allocation_adapter: OptimizationAllocationAdapter = field(
        default_factory=OptimizationAllocationAdapter
    )
    rebalance_planner: RebalancePlanner = field(default_factory=RebalancePlanner)

    def plan(
        self,
        *,
        config: OptimizerConfig,
        optimization_input: OptimizationInput,
        snapshot: PortfolioSnapshot,
        prices: dict[str, Decimal],
    ) -> OptimizedRebalancePlan:
        optimizer = self.optimizer_factory.create(config)
        optimization_result = optimizer.optimize(
            self._with_config_constraints(
                optimization_input=optimization_input,
                config=config,
            )
        )
        allocation = self.allocation_adapter.to_allocation(optimization_result)
        rebalance_plan = self.rebalance_planner.plan(
            snapshot=snapshot,
            allocation=allocation,
            prices=prices,
        )

        return OptimizedRebalancePlan(
            optimization_result=optimization_result,
            allocation=allocation,
            rebalance_plan=rebalance_plan,
        )

    def _with_config_constraints(
        self,
        *,
        optimization_input: OptimizationInput,
        config: OptimizerConfig,
    ) -> OptimizationInput:
        return OptimizationInput(
            universe=optimization_input.universe,
            current_weights=optimization_input.current_weights,
            expected_returns=optimization_input.expected_returns,
            covariance=optimization_input.covariance,
            sector_by_symbol=optimization_input.sector_by_symbol,
            constraints=config.constraints,
            cash_reserve=optimization_input.cash_reserve,
            metadata=optimization_input.metadata,
        )
