"""Expected return objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class ExpectedReturnObjective:
    """Objective that scores weighted expected return."""

    name: str = "expected_return"

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        score = sum(
            (
                target_weights.get(symbol, Decimal("0"))
                * optimization_input.expected_returns.get(symbol, Decimal("0"))
                for symbol in optimization_input.universe
            ),
            Decimal("0"),
        )

        return ObjectiveResult(
            name=self.name,
            score=score,
            components={"expected_return": score},
        )
