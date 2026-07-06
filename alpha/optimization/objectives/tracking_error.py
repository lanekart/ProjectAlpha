"""Benchmark tracking-error objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class TrackingErrorObjective:
    """Objective that scores benchmark-relative active risk."""

    name: str = "tracking_error"

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        benchmark_weights = self._benchmark_weights(optimization_input.metadata)
        symbols = tuple(sorted(set(target_weights) | set(benchmark_weights)))

        score = Decimal("0")
        for row_symbol in symbols:
            row_active_weight = target_weights.get(
                row_symbol,
                Decimal("0"),
            ) - benchmark_weights.get(row_symbol, Decimal("0"))

            if row_active_weight == Decimal("0"):
                continue

            if row_symbol not in optimization_input.covariance:
                raise ValueError(f"missing covariance row for {row_symbol}")

            for column_symbol in symbols:
                column_active_weight = target_weights.get(
                    column_symbol,
                    Decimal("0"),
                ) - benchmark_weights.get(column_symbol, Decimal("0"))

                if column_active_weight == Decimal("0"):
                    continue

                if column_symbol not in optimization_input.covariance[row_symbol]:
                    raise ValueError(
                        f"missing covariance value for {row_symbol}/{column_symbol}"
                    )

                score += (
                    row_active_weight
                    * column_active_weight
                    * optimization_input.covariance[row_symbol][column_symbol]
                )

        return ObjectiveResult(
            name=self.name,
            score=score,
            components={"tracking_error_variance": score},
        )

    def _benchmark_weights(
        self,
        metadata: Mapping[str, object],
    ) -> Mapping[str, Decimal]:
        raw_benchmark_weights = metadata.get("benchmark_weights", {})
        if not isinstance(raw_benchmark_weights, Mapping):
            raise TypeError("benchmark_weights metadata must be a mapping")

        benchmark_weights: dict[str, Decimal] = {}
        for symbol, weight in raw_benchmark_weights.items():
            if not isinstance(symbol, str):
                raise TypeError("benchmark weight symbols must be strings")
            if isinstance(weight, Decimal):
                benchmark_weights[symbol] = weight
            elif isinstance(weight, int | str):
                benchmark_weights[symbol] = Decimal(weight)
            else:
                raise TypeError("benchmark weights must be Decimal, int, or str")

        return benchmark_weights
