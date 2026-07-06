from decimal import Decimal

import pytest

from alpha.portfolio import (
    BlackLittermanOptimizer,
    EqualWeightOptimizer,
    InverseVolatilityOptimizer,
    MaximumSharpeOptimizer,
    MinimumVarianceOptimizer,
    OptimizationInput,
    OptimizerConfig,
    OptimizerFactory,
    OptimizerRegistry,
    PositionLimitConstraint,
    RiskParityOptimizer,
    default_optimizer_registry,
)
from alpha.portfolio.constraints import ConstraintSet
from alpha.portfolio.optimizer import Optimizer


class CustomOptimizer(EqualWeightOptimizer):
    name: str = "custom"


def test_optimizer_config_is_immutable() -> None:
    config = OptimizerConfig(
        name="equal_weight",
        parameters={"example": "value"},
        metadata={"source": "test"},
    )

    with pytest.raises(TypeError):
        config.parameters["example"] = "changed"  # type: ignore[index]

    with pytest.raises(TypeError):
        config.metadata["source"] = "changed"  # type: ignore[index]


def test_optimizer_config_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        OptimizerConfig(name=" ")


def test_registry_registers_and_returns_optimizer() -> None:
    registry = OptimizerRegistry()

    registry.register("custom", CustomOptimizer)

    assert registry.contains("custom")
    assert registry.get("custom") is CustomOptimizer
    assert registry.names() == ("custom",)


def test_registry_rejects_duplicate_registration() -> None:
    registry = OptimizerRegistry()
    registry.register("custom", CustomOptimizer)

    with pytest.raises(ValueError):
        registry.register("custom", CustomOptimizer)


def test_registry_rejects_unknown_optimizer() -> None:
    registry = OptimizerRegistry()

    with pytest.raises(KeyError):
        registry.get("missing")


def test_default_registry_contains_first_party_optimizers() -> None:
    registry = default_optimizer_registry()

    assert registry.get("equal_weight") is EqualWeightOptimizer
    assert registry.get("inverse_volatility") is InverseVolatilityOptimizer
    assert registry.get("risk_parity") is RiskParityOptimizer
    assert registry.get("minimum_variance") is MinimumVarianceOptimizer
    assert registry.get("maximum_sharpe") is MaximumSharpeOptimizer
    assert registry.get("black_litterman") is BlackLittermanOptimizer


def test_factory_creates_optimizer_from_config() -> None:
    factory = OptimizerFactory()

    optimizer = factory.create(OptimizerConfig(name="equal_weight"))

    assert isinstance(optimizer, EqualWeightOptimizer)


def test_factory_passes_optimizer_parameters() -> None:
    factory = OptimizerFactory()

    optimizer = factory.create(
        OptimizerConfig(
            name="risk_parity",
            parameters={
                "max_iterations": 25,
                "tolerance": Decimal("0.01"),
                "step_size": Decimal("0.20"),
            },
        )
    )

    assert isinstance(optimizer, RiskParityOptimizer)
    assert optimizer.max_iterations == 25
    assert optimizer.tolerance == Decimal("0.01")
    assert optimizer.step_size == Decimal("0.20")


def test_factory_passes_maximum_sharpe_parameters() -> None:
    optimizer = OptimizerFactory().create(
        OptimizerConfig(
            name="maximum_sharpe",
            parameters={"risk_free_rate": Decimal("0.03")},
        )
    )

    assert isinstance(optimizer, MaximumSharpeOptimizer)
    assert optimizer.risk_free_rate == Decimal("0.03")


def test_factory_supports_plugin_optimizer_without_engine_changes() -> None:
    registry = OptimizerRegistry()
    registry.register("custom", CustomOptimizer)

    factory = OptimizerFactory(registry=registry)
    optimizer = factory.create(OptimizerConfig(name="custom"))

    assert isinstance(optimizer, CustomOptimizer)


def test_optimizer_config_constraints_remain_independent_from_factory() -> None:
    constraint_set = ConstraintSet(
        constraints=(PositionLimitConstraint(max_weight=Decimal("0.50")),)
    )
    config = OptimizerConfig(name="equal_weight", constraints=constraint_set)

    optimizer = OptimizerFactory().create(config)
    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            constraints=config.constraints,
        )
    )

    assert result.success
    assert result.target_weights["AAPL"] == Decimal("0.5")
    assert result.target_weights["MSFT"] == Decimal("0.5")


def test_factory_returns_optimizer_protocol_instance() -> None:
    optimizer: Optimizer = OptimizerFactory().create(
        OptimizerConfig(name="equal_weight")
    )

    assert optimizer.name == "equal_weight"
