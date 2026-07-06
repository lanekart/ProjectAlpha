"""Black-Litterman portfolio optimizer foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from alpha.optimization.evaluator import ObjectiveEvaluator
from alpha.optimization.objectives.expected_return import ExpectedReturnObjective
from alpha.optimization.objectives.turnover import TurnoverObjective
from alpha.optimization.objectives.variance import VarianceObjective
from alpha.portfolio.constraint_evaluator import ConstraintEvaluator
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
    evaluator: ObjectiveEvaluator = field(default_factory=ObjectiveEvaluator)
    constraint_evaluator: ConstraintEvaluator = field(default_factory=ConstraintEvaluator)
    expected_return_objective: ExpectedReturnObjective = field(
        default_factory=ExpectedReturnObjective
    )
    turnover_objective: TurnoverObjective = field(default_factory=TurnoverObjective)
    variance_objective: VarianceObjective = field(default_factory=VarianceObjective)

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
        objective_input = optimization_input.with_expected_returns(posterior_returns)
        expected_return_result = self.evaluator.evaluate(
            objective=self.expected_return_objective,
            optimization_input=objective_input,
            target_weights=target_weights,
        )
        turnover_result = self.evaluator.evaluate(
            objective=self.turnover_objective,
            optimization_input=optimization_input,
            target_weights=target_weights,
        )
        variance_result = self.evaluator.evaluate(
            objective=self.variance_objective,
            optimization_input=optimization_input,
            target_weights=target_weights,
        )
        constraint_result = self.constraint_evaluator.evaluate_input(
            optimization_input=optimization_input,
            target_weights=target_weights,
        )

        return OptimizationResult(
            target_weights=target_weights,
            success=constraint_result.passed,
            expected_turnover=turnover_result.score,
            cash_weight=optimization_input.cash_reserve,
            constraint_violations=constraint_result.violations,
            metadata={
                "optimizer": self.name,
                "views": str(len(self.views)),
                "objectives": {
                    expected_return_result.name: expected_return_result.score,
                    turnover_result.name: turnover_result.score,
                    variance_result.name: variance_result.score,
                },
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
        """Calculate turnover for backward-compatible internal tests."""

        universe = tuple(sorted(set(current_weights) | set(target_weights)))
        return self.turnover_objective.evaluate(
            optimization_input=OptimizationInput(
                universe=universe,
                current_weights=current_weights,
            ),
            target_weights=target_weights,
        ).score
