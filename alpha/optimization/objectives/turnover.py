"""Portfolio turnover objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class TurnoverObjective:
    """Objective that scores expected turnover."""

    name: str = "turnover"

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        symbols = set(optimization_input.current_weights) | set(target_weights)
        score = sum(
            abs(
                target_weights.get(symbol, Decimal("0"))
                - optimization_input.current_weights.get(symbol, Decimal("0"))
            )
            for symbol in symbols
        ) / Decimal("2")

        return ObjectiveResult(
            name=self.name,
            score=score,
            components={"turnover": score},
        )
