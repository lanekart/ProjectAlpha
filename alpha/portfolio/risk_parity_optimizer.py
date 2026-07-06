"""Risk parity portfolio optimizer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext

from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class RiskParityOptimizer(Optimizer):
    """Optimizer that targets equal risk contribution across assets."""

    name: str = "risk_parity"
    max_iterations: int = 500
    tolerance: Decimal = Decimal("0.000001")
    step_size: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.tolerance <= Decimal("0"):
            raise ValueError("tolerance must be positive")
        if self.step_size <= Decimal("0"):
            raise ValueError("step_size must be positive")

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build target weights that approximate equal risk contribution."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        self._validate_covariance(
            universe=optimization_input.universe,
            covariance=optimization_input.covariance,
        )

        unit_weights = self._solve_unit_risk_parity_weights(
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

    def _solve_unit_risk_parity_weights(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        weight = Decimal("1") / Decimal(len(universe))
        weights = {symbol: weight for symbol in universe}

        for _ in range(self.max_iterations):
            contributions = self._risk_contributions(
                universe=universe,
                covariance=covariance,
                weights=weights,
            )
            target_contribution = Decimal("1") / Decimal(len(universe))
            max_error = max(
                abs(contribution - target_contribution)
                for contribution in contributions.values()
            )

            if max_error <= self.tolerance:
                return weights

            adjusted_weights = {
                symbol: weights[symbol]
                * (
                    Decimal("1")
                    + self.step_size * (target_contribution - contributions[symbol])
                )
                for symbol in universe
            }
            weights = self._normalize_positive_weights(adjusted_weights)

        return weights

    def _risk_contributions(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
        weights: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        marginal_risk = {
            symbol: sum(
                covariance[symbol][other_symbol] * weights[other_symbol]
                for other_symbol in universe
            )
            for symbol in universe
        }
        portfolio_variance = sum(
            weights[symbol] * marginal_risk[symbol] for symbol in universe
        )

        if portfolio_variance <= Decimal("0"):
            raise ValueError("portfolio variance must be positive")

        return {
            symbol: weights[symbol] * marginal_risk[symbol] / portfolio_variance
            for symbol in universe
        }

    def _normalize_positive_weights(
        self,
        weights: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        positive_weights = {
            symbol: max(weight, Decimal("0.0000000001"))
            for symbol, weight in weights.items()
        }
        total_weight = sum(positive_weights.values(), Decimal("0"))

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

        self._validate_positive_portfolio_variance(
            universe=universe,
            covariance=covariance,
        )

    def _validate_positive_portfolio_variance(
        self,
        *,
        universe: tuple[str, ...],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> None:
        with localcontext() as context:
            context.prec = 40
            weight = Decimal("1") / Decimal(len(universe))
            weights = {symbol: weight for symbol in universe}
            variance = sum(
                weights[symbol]
                * sum(
                    covariance[symbol][other_symbol] * weights[other_symbol]
                    for other_symbol in universe
                )
                for symbol in universe
            )

        if variance <= Decimal("0"):
            raise ValueError("portfolio variance must be positive")

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
