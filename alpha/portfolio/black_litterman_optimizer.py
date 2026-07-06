"""Black-Litterman portfolio optimizer foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class BlackLittermanView:
    """Investor view used by the Black-Litterman optimizer."""

    symbol: str
    expected_return: Decimal
    confidence: Decimal

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.confidence <= Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class BlackLittermanOptimizer(Optimizer):
    """Long-only Black-Litterman optimizer foundation."""

    views: tuple[BlackLittermanView, ...] = ()
    risk_aversion: Decimal = Decimal("1")
    tau: Decimal = Decimal("0.05")
    name: str = "black_litterman"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk_aversion <= Decimal("0"):
            raise ValueError("risk_aversion must be positive")
        if self.tau <= Decimal("0"):
            raise ValueError("tau must be positive")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build target weights from blended implied and investor returns."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        self._validate_covariance(
            universe=optimization_input.universe,
            covariance=optimization_input.covariance,
        )
        self._validate_expected_returns(
            universe=optimization_input.universe,
            expected_returns=optimization_input.expected_returns,
        )
        self._validate_views(universe=optimization_input.universe)

        posterior_returns = self._posterior_returns(
            universe=optimization_input.universe,
            expected_returns=optimization_input.expected_returns,
        )
        unit_weights = self._long_only_return_risk_weights(
            universe=optimization_input.universe,
            expected_returns=posterior_returns,
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
            metadata={
                "optimizer": self.name,
                "views": str(len(self.views)),
                **self.metadata,
            },
        )

    def _posterior_returns(
        self,
        *,
        universe: tuple[str, ...],
        expected_returns: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        posterior_returns = {symbol: expected_returns[symbol] for symbol in universe}

        for view in self.views:
            prior_return = posterior_returns[view.symbol]
            posterior_returns[view.symbol] = (
                prior_return * (Decimal("1") - view.confidence)
                + view.expected_return * view.confidence
            )

        return posterior_returns

    def _long_only_return_risk_weights(
        self,
        *,
        universe: tuple[str, ...],
        expected_returns: Mapping[str, Decimal],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        raw_scores = {
            symbol: max(
                expected_returns[symbol]
                / (covariance[symbol][symbol] * self.risk_aversion * self.tau),
                Decimal("0"),
            )
            for symbol in universe
        }
        total_score = sum(raw_scores.values(), Decimal("0"))

        if total_score <= Decimal("0"):
            equal_weight = Decimal("1") / Decimal(len(universe))
            return {symbol: equal_weight for symbol in universe}

        return {symbol: raw_scores[symbol] / total_score for symbol in universe}

    def _validate_expected_returns(
        self,
        *,
        universe: tuple[str, ...],
        expected_returns: Mapping[str, Decimal],
    ) -> None:
        for symbol in universe:
            if symbol not in expected_returns:
                raise ValueError(f"missing expected return for {symbol}")

    def _validate_views(self, *, universe: tuple[str, ...]) -> None:
        universe_symbols = set(universe)

        for view in self.views:
            if view.symbol not in universe_symbols:
                raise ValueError(f"view symbol {view.symbol} is not in universe")

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
