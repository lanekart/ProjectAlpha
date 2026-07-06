"""Objective evaluation service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective import Objective
from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class ObjectiveEvaluator:
    """Stateless service for evaluating portfolio objective functions."""

    def evaluate(
        self,
        objective: Objective,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        """Evaluate target weights against an objective."""

        return objective.evaluate(
            optimization_input=optimization_input,
            target_weights=target_weights,
        )

    def score(
        self,
        objective: Objective,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> Decimal:
        """Return only the objective score for target weights."""

        return self.evaluate(
            objective=objective,
            optimization_input=optimization_input,
            target_weights=target_weights,
        ).score
