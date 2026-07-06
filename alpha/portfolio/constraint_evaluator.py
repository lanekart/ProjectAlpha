"""Portfolio constraint evaluation service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.portfolio.constraint_result import ConstraintResult
from alpha.portfolio.constraints import ConstraintSet
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class ConstraintEvaluator:
    """Stateless service for evaluating portfolio constraints."""

    def evaluate(
        self,
        *,
        constraints: ConstraintSet,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ConstraintResult:
        """Evaluate target weights against a constraint set."""

        violations = constraints.validate(
            target_weights=target_weights,
            current_weights=optimization_input.current_weights,
            sector_by_symbol=optimization_input.sector_by_symbol,
            cash_weight=optimization_input.cash_reserve,
        )

        return ConstraintResult(
            violations=violations,
            metadata={"constraint_count": len(constraints.constraints)},
        )

    def evaluate_input(
        self,
        *,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ConstraintResult:
        """Evaluate target weights against constraints carried by optimizer input."""

        return self.evaluate(
            constraints=optimization_input.constraints,
            optimization_input=optimization_input,
            target_weights=target_weights,
        )
