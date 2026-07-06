"""Public optimization package boundary.

This package is the stable import surface for portfolio optimizers, optimizer
infrastructure, and reusable optimization objectives. Implementations are
currently hosted in alpha.portfolio for backward compatibility and will be
migrated behind this boundary in later behavior-preserving refactors.
"""

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
from alpha.portfolio.black_litterman_optimizer import (
    BlackLittermanOptimizer,
    BlackLittermanView,
)
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
from alpha.portfolio.minimum_variance_optimizer import MinimumVarianceOptimizer
from alpha.portfolio.optimization_result import ConstraintViolation, OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.optimizer_factory import OptimizerFactory
from alpha.portfolio.optimizer_registry import (
    OptimizerRegistry,
    default_optimizer_registry,
)
from alpha.portfolio.risk_parity_optimizer import RiskParityOptimizer

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
