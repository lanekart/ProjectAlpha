"""Public optimization package boundary.

This package is the stable import surface for portfolio optimizers, optimizer
infrastructure, and reusable optimization objectives. Portfolio implementations
are loaded lazily to keep this public facade from creating circular imports when
portfolio modules depend on optimization internals.
"""

from __future__ import annotations

from typing import Any

from alpha.optimization.evaluator import ObjectiveEvaluator
from alpha.optimization.objective import Objective
from alpha.optimization.objective_result import ObjectiveResult
from alpha.optimization.objectives import (
    ConcentrationObjective,
    ExpectedReturnObjective,
    TrackingErrorObjective,
    TransactionCostObjective,
    TurnoverObjective,
    VarianceObjective,
)
from alpha.optimization.weighted_objective import (
    WeightedObjective,
    WeightedObjectiveComponent,
)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "BlackLittermanOptimizer": (
        "alpha.portfolio.black_litterman_optimizer",
        "BlackLittermanOptimizer",
    ),
    "BlackLittermanView": (
        "alpha.portfolio.black_litterman_optimizer",
        "BlackLittermanView",
    ),
    "CashReserveConstraint": (
        "alpha.portfolio.constraints",
        "CashReserveConstraint",
    ),
    "ConstraintSet": ("alpha.portfolio.constraints", "ConstraintSet"),
    "ConstraintViolation": (
        "alpha.portfolio.optimization_result",
        "ConstraintViolation",
    ),
    "EqualWeightOptimizer": (
        "alpha.portfolio.equal_weight_optimizer",
        "EqualWeightOptimizer",
    ),
    "InverseVolatilityOptimizer": (
        "alpha.portfolio.inverse_volatility_optimizer",
        "InverseVolatilityOptimizer",
    ),
    "MinimumVarianceOptimizer": (
        "alpha.portfolio.minimum_variance_optimizer",
        "MinimumVarianceOptimizer",
    ),
    "OptimizationInput": ("alpha.portfolio.optimizer", "OptimizationInput"),
    "OptimizationResult": (
        "alpha.portfolio.optimization_result",
        "OptimizationResult",
    ),
    "Optimizer": ("alpha.portfolio.optimizer", "Optimizer"),
    "OptimizerConfig": ("alpha.portfolio.optimizer_config", "OptimizerConfig"),
    "OptimizerFactory": ("alpha.portfolio.optimizer_factory", "OptimizerFactory"),
    "OptimizerRegistry": (
        "alpha.portfolio.optimizer_registry",
        "OptimizerRegistry",
    ),
    "PortfolioConstraint": ("alpha.portfolio.constraints", "PortfolioConstraint"),
    "PositionLimitConstraint": (
        "alpha.portfolio.constraints",
        "PositionLimitConstraint",
    ),
    "RiskParityOptimizer": (
        "alpha.portfolio.risk_parity_optimizer",
        "RiskParityOptimizer",
    ),
    "SectorLimitConstraint": ("alpha.portfolio.constraints", "SectorLimitConstraint"),
    "TurnoverConstraint": ("alpha.portfolio.constraints", "TurnoverConstraint"),
    "default_optimizer_registry": (
        "alpha.portfolio.optimizer_registry",
        "default_optimizer_registry",
    ),
}

__all__ = [
    "BlackLittermanOptimizer",
    "BlackLittermanView",
    "CashReserveConstraint",
    "ConcentrationObjective",
    "ConstraintSet",
    "ConstraintViolation",
    "EqualWeightOptimizer",
    "ExpectedReturnObjective",
    "InverseVolatilityOptimizer",
    "MinimumVarianceOptimizer",
    "Objective",
    "ObjectiveEvaluator",
    "ObjectiveResult",
    "OptimizationInput",
    "OptimizationResult",
    "Optimizer",
    "OptimizerConfig",
    "OptimizerFactory",
    "OptimizerRegistry",
    "PortfolioConstraint",
    "PositionLimitConstraint",
    "RiskParityOptimizer",
    "SectorLimitConstraint",
    "TrackingErrorObjective",
    "TransactionCostObjective",
    "TurnoverConstraint",
    "TurnoverObjective",
    "VarianceObjective",
    "WeightedObjective",
    "WeightedObjectiveComponent",
    "default_optimizer_registry",
]


def __getattr__(name: str) -> Any:
    """Load portfolio-backed public exports lazily."""

    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute_name])
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
