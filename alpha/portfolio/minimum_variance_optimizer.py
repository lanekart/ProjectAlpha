"""Minimum variance portfolio optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext

from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class MinimumVarianceOptimizer(Optimizer):
    """Optimizer that minimizes portfolio variance using covariance data."""

    name: str = "minimum_variance"

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build target weights using inverse covariance approximation."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        self._validate_covariance(
            universe=optimization_input.universe,
            covariance=optimization_input.covariance,
        )

        unit_weights = self._solve_unit_minimum_variance_weights(
            universe=optimization_input.universe,
            covariance=optimization_input.covariance,
        )
        target_weights = {
            symbol: unit_weights[symbol] * investable_weight
            for symbol in optimization_input.universe
        }

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

    def _solve_unit_minimum_variance_weights(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        if len(universe) == 1:
            return {universe[0]: Decimal("1")}

        inverse_covariance = self._invert_matrix(
            self._covariance_matrix(universe=universe, covariance=covariance)
        )

        raw_weights: list[Decimal] = [
            self._row_sum(inverse_covariance[row_index])
            for row_index in range(len(universe))
        ]

        total_raw_weight = sum(raw_weights, Decimal("0"))
        if total_raw_weight == Decimal("0"):
            raise ValueError("minimum variance weights cannot be normalized")

        weights: dict[str, Decimal] = {
            symbol: raw_weights[index] / total_raw_weight
            for index, symbol in enumerate(universe)
        }

        if any(weight < Decimal("0") for weight in weights.values()):
            return self._normalize_positive_weights(weights)

        return weights

    def _row_sum(self, row: list[Decimal]) -> Decimal:
        return sum(row, Decimal("0"))

    def _covariance_matrix(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> list[list[Decimal]]:
        return [
            [covariance[row_symbol][column_symbol] for column_symbol in universe]
            for row_symbol in universe
        ]

    def _invert_matrix(self, matrix: list[list[Decimal]]) -> list[list[Decimal]]:
        size = len(matrix)
        augmented: list[list[Decimal]] = [
            [
                *matrix[row_index],
                *[
                    Decimal("1") if row_index == column_index else Decimal("0")
                    for column_index in range(size)
                ],
            ]
            for row_index in range(size)
        ]

        with localcontext() as context:
            context.prec = 40

            for pivot_index in range(size):
                pivot_row = self._find_pivot_row(
                    augmented=augmented,
                    pivot_index=pivot_index,
                )
                if pivot_row != pivot_index:
                    augmented[pivot_index], augmented[pivot_row] = (
                        augmented[pivot_row],
                        augmented[pivot_index],
                    )

                pivot = augmented[pivot_index][pivot_index]
                if pivot == Decimal("0"):
                    raise ValueError("covariance matrix is singular")

                augmented[pivot_index] = [
                    value / pivot for value in augmented[pivot_index]
                ]

                for row_index in range(size):
                    if row_index == pivot_index:
                        continue

                    factor = augmented[row_index][pivot_index]
                    augmented[row_index] = [
                        current_value - factor * pivot_value
                        for current_value, pivot_value in zip(
                            augmented[row_index],
                            augmented[pivot_index],
                            strict=True,
                        )
                    ]

        return [row[size:] for row in augmented]

    def _find_pivot_row(
        self,
        *,
        augmented: list[list[Decimal]],
        pivot_index: int,
    ) -> int:
        pivot_candidates = range(pivot_index, len(augmented))
        return max(
            pivot_candidates,
            key=lambda row_index: abs(augmented[row_index][pivot_index]),
        )

    def _normalize_positive_weights(
        self,
        weights: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        positive_weights = {
            symbol: max(weight, Decimal("0")) for symbol, weight in weights.items()
        }
        total_weight = sum(positive_weights.values(), Decimal("0"))

        if total_weight <= Decimal("0"):
            raise ValueError("minimum variance weights cannot be long-only")

        return {
            symbol: weight / total_weight for symbol, weight in positive_weights.items()
        }

    def _validate_covariance(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> None:
        for symbol in universe:
            if symbol not in covariance:
                raise ValueError(f"missing covariance row for {symbol}")

            for other_symbol in universe:
                if other_symbol not in covariance[symbol]:
                    raise ValueError(
                        f"missing covariance value for {symbol}/{other_symbol}"
                    )

            if covariance[symbol][symbol] <= Decimal("0"):
                raise ValueError(f"variance for {symbol} must be positive")

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
