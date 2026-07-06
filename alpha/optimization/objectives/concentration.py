"""Portfolio concentration objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class ConcentrationObjective:
    """Objective that scores Herfindahl-Hirschman concentration."""

    name: str = "concentration"

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        del optimization_input

        score = sum(
            (weight * weight for weight in target_weights.values()),
            Decimal("0"),
        )

        return ObjectiveResult(
            name=self.name,
            score=score,
            components={"hhi": score},
        )
