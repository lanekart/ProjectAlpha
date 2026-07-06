"""Equal weight portfolio optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from alpha.optimization.evaluator import ObjectiveEvaluator
from alpha.optimization.objectives.turnover import TurnoverObjective
from alpha.portfolio.constraint_evaluator import ConstraintEvaluator
from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class EqualWeightOptimizer(Optimizer):
    """Optimizer that assigns equal weight to every symbol in the universe."""

    name: str = "equal_weight"
    evaluator: ObjectiveEvaluator = field(default_factory=ObjectiveEvaluator)
    constraint_evaluator: ConstraintEvaluator = field(
        default_factory=ConstraintEvaluator
    )
    turnover_objective: TurnoverObjective = field(default_factory=TurnoverObjective)

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build equal target weights across the supplied universe."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        target_weights = self._target_weights(
            universe=optimization_input.universe,
            investable_weight=investable_weight,
        )
        turnover_result = self.evaluator.evaluate(
            objective=self.turnover_objective,
            optimization_input=optimization_input,
            target_weights=target_weights,
        )
        constraint_result = self.constraint_evaluator.evaluate_input(
            optimization_input=optimization_input,
            target_weights=target_weights,
        )

        return OptimizationResult(
            target_weights=target_weights,
            success=constraint_result.passed,
            expected_turnover=turnover_result.score,
            cash_weight=optimization_input.cash_reserve,
            constraint_violations=constraint_result.violations,
            metadata={
                "optimizer": self.name,
                "objectives": {turnover_result.name: turnover_result.score},
            },
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
        """Calculate turnover for backward-compatible internal tests."""

        universe = tuple(sorted(set(current_weights) | set(target_weights)))
        return self.turnover_objective.evaluate(
            optimization_input=OptimizationInput(
                universe=universe,
                current_weights=current_weights,
            ),
            target_weights=target_weights,
        ).score
