"""Inverse volatility portfolio optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class InverseVolatilityOptimizer(Optimizer):
    """Optimizer that weights assets inversely to their volatility."""

    name: str = "inverse_volatility"

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build target weights from diagonal covariance volatility estimates."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        inverse_volatility_by_symbol = self._calculate_inverse_volatilities(
            universe=optimization_input.universe,
            covariance=optimization_input.covariance,
        )
        total_inverse_volatility = sum(
            inverse_volatility_by_symbol.values(),
            Decimal("0"),
        )

        if total_inverse_volatility <= Decimal("0"):
            raise ValueError("total inverse volatility must be positive")

        target_weights = {
            symbol: (
                inverse_volatility_by_symbol[symbol]
                / total_inverse_volatility
                * investable_weight
            )
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

    def _calculate_inverse_volatilities(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        inverse_volatility_by_symbol: dict[str, Decimal] = {}

        for symbol in universe:
            variance = covariance.get(symbol, {}).get(symbol)
            if variance is None:
                raise ValueError(f"missing variance for {symbol}")
            if variance <= Decimal("0"):
                raise ValueError(f"variance for {symbol} must be positive")

            inverse_volatility_by_symbol[symbol] = Decimal("1") / variance.sqrt()

        return inverse_volatility_by_symbol

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
