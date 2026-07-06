"""Portfolio variance objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class VarianceObjective:
    """Objective that scores portfolio variance."""

    name: str = "variance"

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        score = Decimal("0")

        for row_symbol in optimization_input.universe:
            row_weight = target_weights.get(row_symbol, Decimal("0"))
            if row_weight == Decimal("0"):
                continue

            if row_symbol not in optimization_input.covariance:
                raise ValueError(f"missing covariance row for {row_symbol}")

            for column_symbol in optimization_input.universe:
                column_weight = target_weights.get(column_symbol, Decimal("0"))
                if column_weight == Decimal("0"):
                    continue

                if column_symbol not in optimization_input.covariance[row_symbol]:
                    raise ValueError(
                        f"missing covariance value for {row_symbol}/{column_symbol}"
                    )

                score += (
                    row_weight
                    * column_weight
                    * optimization_input.covariance[row_symbol][column_symbol]
                )

        return ObjectiveResult(
            name=self.name,
            score=score,
            components={"variance": score},
        )
