from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.portfolio.allocation.target import AllocationTarget, PortfolioAllocation
from alpha.portfolio.optimization_result import OptimizationResult


@dataclass(frozen=True, slots=True)
class OptimizationAllocationAdapter:
    """
    Converts optimizer output into a portfolio allocation.

    This adapter deliberately lives in the allocation layer so that optimizers
    remain independent from backtest execution, broker simulation, and accounting.
    """

    include_zero_weight_targets: bool = False

    def to_allocation(self, result: OptimizationResult) -> PortfolioAllocation:
        if not result.success:
            raise ValueError("cannot convert unsuccessful optimization result")

        targets: list[AllocationTarget] = []

        for symbol, weight in sorted(result.target_weights.items()):
            if not self.include_zero_weight_targets and weight == Decimal("0"):
                continue

            targets.append(
                AllocationTarget(
                    symbol=symbol,
                    weight=weight,
                )
            )

        return PortfolioAllocation(targets=tuple(targets))
