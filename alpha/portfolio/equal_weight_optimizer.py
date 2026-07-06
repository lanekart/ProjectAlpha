"""Equal weight portfolio optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class EqualWeightOptimizer(Optimizer):
    """Optimizer that assigns equal weight to every symbol in the universe."""

    name: str = "equal_weight"

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build equal target weights across the supplied universe."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        target_weights = self._target_weights(
            universe=optimization_input.universe,
            investable_weight=investable_weight,
        )
        expected_turnover = self._calculate_turnover(
            current_weights=optimization_input.current_weights,
            target_weights=target_weights,
        )

        violations = optimization_input.constraints.validate(
            target_weights=target_weights,
            current_weights=optimization_input.current_weights,
            sector_by_symbol=optimization_input.sector_by_symbol,
            cash_weight=optimization_input.cash_reserve,
        )

        return OptimizationResult(
            target_weights=target_weights,
            success=len(violations) == 0,
            expected_turnover=expected_turnover,
            cash_weight=optimization_input.cash_reserve,
            constraint_violations=violations,
            metadata={"optimizer": self.name},
        )

    def _target_weights(
        self,
        *,
        universe: tuple[str, ...],
        investable_weight: Decimal,
    ) -> dict[str, Decimal]:
        per_symbol_weight = investable_weight / Decimal(len(universe))
        return {symbol: per_symbol_weight for symbol in universe}

    def _calculate_turnover(
        self,
        *,
        current_weights: Mapping[str, Decimal],
        target_weights: Mapping[str, Decimal],
    ) -> Decimal:
        normalized_current: dict[str, Decimal] = dict(current_weights)
        symbols = set(normalized_current) | set(target_weights)

        return sum(
            abs(
                target_weights.get(symbol, Decimal("0"))
                - normalized_current.get(symbol, Decimal("0"))
            )
            for symbol in symbols
        ) / Decimal("2")
