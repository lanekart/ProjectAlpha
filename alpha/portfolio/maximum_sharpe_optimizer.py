"""Maximum Sharpe portfolio optimizer foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from alpha.optimization.evaluator import ObjectiveEvaluator
from alpha.optimization.objectives.expected_return import ExpectedReturnObjective
from alpha.optimization.objectives.turnover import TurnoverObjective
from alpha.optimization.objectives.variance import VarianceObjective
from alpha.portfolio.constraint_evaluator import ConstraintEvaluator
from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class MaximumSharpeOptimizer(Optimizer):
    """Long-only optimizer that favors assets with high excess return per risk."""

    risk_free_rate: Decimal = Decimal("0")
    name: str = "maximum_sharpe"
    evaluator: ObjectiveEvaluator = field(default_factory=ObjectiveEvaluator)
    constraint_evaluator: ConstraintEvaluator = field(
        default_factory=ConstraintEvaluator
    )
    expected_return_objective: ExpectedReturnObjective = field(
        default_factory=ExpectedReturnObjective
    )
    turnover_objective: TurnoverObjective = field(default_factory=TurnoverObjective)
    variance_objective: VarianceObjective = field(default_factory=VarianceObjective)

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Build target weights from excess-return-to-volatility scores."""

        investable_weight = Decimal("1") - optimization_input.cash_reserve
        if investable_weight < Decimal("0"):
            raise ValueError("cash_reserve cannot exceed 1")

        self._validate_inputs(
            universe=optimization_input.universe,
            expected_returns=optimization_input.expected_returns,
            covariance=optimization_input.covariance,
        )

        unit_weights = self._solve_unit_weights(
            universe=optimization_input.universe,
            expected_returns=optimization_input.expected_returns,
            covariance=optimization_input.covariance,
        )
        target_weights = {
            symbol: unit_weights[symbol] * investable_weight
            for symbol in optimization_input.universe
        }
        expected_return_result = self.evaluator.evaluate(
            objective=self.expected_return_objective,
            optimization_input=optimization_input,
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
                "risk_free_rate": self.risk_free_rate,
                "objectives": {
                    expected_return_result.name: expected_return_result.score,
                    turnover_result.name: turnover_result.score,
                    variance_result.name: variance_result.score,
                },
            },
        )

    def _solve_unit_weights(
        self,
        *,
        universe: tuple[str, ...],
        expected_returns: Mapping[str, Decimal],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        scores = {
            symbol: self._risk_adjusted_score(
                expected_return=expected_returns[symbol],
                variance=covariance[symbol][symbol],
            )
            for symbol in universe
        }
        positive_scores = {
            symbol: max(score, Decimal("0")) for symbol, score in scores.items()
        }
        total_score = sum(positive_scores.values(), Decimal("0"))

        if total_score <= Decimal("0"):
            return self._equal_unit_weights(universe)

        return {
            symbol: positive_scores[symbol] / total_score for symbol in universe
        }

    def _risk_adjusted_score(
        self,
        *,
        expected_return: Decimal,
        variance: Decimal,
    ) -> Decimal:
        return (expected_return - self.risk_free_rate) / variance.sqrt()

    def _equal_unit_weights(self, universe: tuple[str, ...]) -> dict[str, Decimal]:
        weight = Decimal("1") / Decimal(len(universe))
        return {symbol: weight for symbol in universe}

    def _validate_inputs(
        self,
        *,
        universe: tuple[str, ...],
        expected_returns: Mapping[str, Decimal],
        covariance: Mapping[str, Mapping[str, Decimal]],
    ) -> None:
        for symbol in universe:
            if symbol not in expected_returns:
                raise ValueError(f"missing expected return for {symbol}")
            if symbol not in covariance:
                raise ValueError(f"missing covariance row for {symbol}")
            if symbol not in covariance[symbol]:
                raise ValueError(f"missing variance for {symbol}")
            if covariance[symbol][symbol] <= Decimal("0"):
                raise ValueError(f"variance for {symbol} must be positive")
