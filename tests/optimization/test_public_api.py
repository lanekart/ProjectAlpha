from decimal import Decimal

from alpha.optimization import (
    BlackLittermanOptimizer,
    ConstraintEvaluator,
    ConstraintResult,
    EqualWeightOptimizer,
    InverseVolatilityOptimizer,
    MaximumSharpeOptimizer,
    MinimumVarianceOptimizer,
    OptimizationInput,
    OptimizerConfig,
    OptimizerFactory,
    RiskParityOptimizer,
    default_optimizer_registry,
)


def test_optimization_package_exports_first_party_optimizers() -> None:
    registry = default_optimizer_registry()

    assert registry.get("equal_weight") is EqualWeightOptimizer
    assert registry.get("inverse_volatility") is InverseVolatilityOptimizer
    assert registry.get("risk_parity") is RiskParityOptimizer
    assert registry.get("minimum_variance") is MinimumVarianceOptimizer
    assert registry.get("maximum_sharpe") is MaximumSharpeOptimizer
    assert registry.get("black_litterman") is BlackLittermanOptimizer


def test_optimization_package_exports_constraint_evaluation_primitives() -> None:
    assert (
        ConstraintEvaluator()
        .evaluate_input(
            optimization_input=OptimizationInput(universe=("RELIANCE",)),
            target_weights={"RELIANCE": Decimal("1")},
        )
        .passed
    )
    assert ConstraintResult().passed


def test_optimization_package_factory_creates_optimizer() -> None:
    optimizer = OptimizerFactory().create(OptimizerConfig(name="equal_weight"))

    result = optimizer.optimize(
        OptimizationInput(
            universe=("RELIANCE", "TCS"),
        )
    )

    assert result.success
    assert result.target_weights["RELIANCE"] == Decimal("0.5")
    assert result.target_weights["TCS"] == Decimal("0.5")


def test_optimization_package_factory_creates_maximum_sharpe_optimizer() -> None:
    optimizer = OptimizerFactory().create(OptimizerConfig(name="maximum_sharpe"))

    assert isinstance(optimizer, MaximumSharpeOptimizer)
