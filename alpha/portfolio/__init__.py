"""Portfolio construction domain."""

from __future__ import annotations

from typing import Any

from alpha.portfolio.black_litterman_optimizer import (
    BlackLittermanOptimizer,
    BlackLittermanView,
)
from alpha.portfolio.constraint_evaluator import ConstraintEvaluator
from alpha.portfolio.constraint_result import ConstraintResult
from alpha.portfolio.constraints import (
    CashReserveConstraint,
    ConstraintSet,
    PortfolioConstraint,
    PositionLimitConstraint,
    SectorLimitConstraint,
    TurnoverConstraint,
)
from alpha.portfolio.equal_weight_optimizer import EqualWeightOptimizer
from alpha.portfolio.inverse_volatility_optimizer import InverseVolatilityOptimizer
from alpha.portfolio.maximum_sharpe_optimizer import MaximumSharpeOptimizer
from alpha.portfolio.minimum_variance_optimizer import MinimumVarianceOptimizer
from alpha.portfolio.optimization_diagnostics import OptimizationDiagnostics
from alpha.portfolio.optimization_result import ConstraintViolation, OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer
from alpha.portfolio.optimizer_benchmark import (
    OptimizerBenchmarkMetric,
    OptimizerBenchmarkReport,
    OptimizerBenchmarkRun,
    OptimizerBenchmarkScenario,
    OptimizerBenchmarkService,
    OptimizerBenchmarkSummary,
)
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.optimizer_factory import OptimizerFactory
from alpha.portfolio.optimizer_registry import (
    OptimizerRegistry,
    default_optimizer_registry,
)
from alpha.portfolio.risk_parity_optimizer import RiskParityOptimizer

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "OptimizerComparisonEntry": (
        "alpha.portfolio.optimizer_comparison",
        "OptimizerComparisonEntry",
    ),
    "OptimizerComparisonReport": (
        "alpha.portfolio.optimizer_comparison",
        "OptimizerComparisonReport",
    ),
    "OptimizerComparisonService": (
        "alpha.portfolio.optimizer_comparison",
        "OptimizerComparisonService",
    ),
    "OptimizerSelection": (
        "alpha.portfolio.optimizer_selection",
        "OptimizerSelection",
    ),
    "OptimizerSelectionCriteria": (
        "alpha.portfolio.optimizer_selection",
        "OptimizerSelectionCriteria",
    ),
    "OptimizerSelectionResult": (
        "alpha.portfolio.optimizer_selection",
        "OptimizerSelectionResult",
    ),
    "OptimizerSelectionService": (
        "alpha.portfolio.optimizer_selection",
        "OptimizerSelectionService",
    ),
}

__all__ = [
    "BlackLittermanOptimizer",
    "BlackLittermanView",
    "CashReserveConstraint",
    "ConstraintEvaluator",
    "ConstraintResult",
    "ConstraintSet",
    "ConstraintViolation",
    "EqualWeightOptimizer",
    "InverseVolatilityOptimizer",
    "MaximumSharpeOptimizer",
    "MinimumVarianceOptimizer",
    "OptimizationDiagnostics",
    "OptimizationInput",
    "OptimizationResult",
    "Optimizer",
    "OptimizerBenchmarkMetric",
    "OptimizerBenchmarkReport",
    "OptimizerBenchmarkRun",
    "OptimizerBenchmarkScenario",
    "OptimizerBenchmarkService",
    "OptimizerBenchmarkSummary",
    "OptimizerComparisonEntry",
    "OptimizerComparisonReport",
    "OptimizerComparisonService",
    "OptimizerConfig",
    "OptimizerFactory",
    "OptimizerRegistry",
    "OptimizerSelection",
    "OptimizerSelectionCriteria",
    "OptimizerSelectionResult",
    "OptimizerSelectionService",
    "PortfolioConstraint",
    "PositionLimitConstraint",
    "RiskParityOptimizer",
    "SectorLimitConstraint",
    "TurnoverConstraint",
    "default_optimizer_registry",
]


def __getattr__(name: str) -> Any:
    """Load optional portfolio exports lazily."""

    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute_name])
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
