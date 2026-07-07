from __future__ import annotations

import pytest

from alpha.trading_signals import (
    StrategyDefinition,
    StrategyRegistry,
    default_strategy_registry,
)


def test_default_strategy_registry_exposes_momentum_strategy() -> None:
    registry = default_strategy_registry()

    assert registry.names == ("momentum",)
    assert "momentum" in registry
    assert " Momentum " in registry

    strategy = registry.get("momentum")
    assert strategy.name == "momentum"
    assert strategy.display_name == "Momentum"
    assert strategy.supports_backtest is True
    assert strategy.supports_signal_generation is True
    assert strategy.minimum_history_days == 20


def test_strategy_registry_is_deterministically_ordered() -> None:
    registry = StrategyRegistry(
        (
            StrategyDefinition(
                name="value",
                display_name="Value",
                description="Value strategy.",
                supports_backtest=True,
                supports_signal_generation=False,
                minimum_history_days=90,
            ),
            StrategyDefinition(
                name="momentum",
                display_name="Momentum",
                description="Momentum strategy.",
                supports_backtest=True,
                supports_signal_generation=True,
                minimum_history_days=20,
            ),
        )
    )

    assert registry.names == ("momentum", "value")
    assert tuple(strategy.name for strategy in registry) == ("momentum", "value")


def test_strategy_registry_rejects_duplicates() -> None:
    first = StrategyDefinition(
        name="momentum",
        display_name="Momentum",
        description="Momentum strategy.",
        supports_backtest=True,
        supports_signal_generation=True,
        minimum_history_days=20,
    )
    second = StrategyDefinition(
        name=" Momentum ",
        display_name="Momentum Duplicate",
        description="Duplicate strategy.",
        supports_backtest=True,
        supports_signal_generation=True,
        minimum_history_days=20,
    )

    with pytest.raises(ValueError, match="duplicate strategy"):
        StrategyRegistry((first, second))


def test_strategy_definition_rejects_invalid_history_window() -> None:
    with pytest.raises(ValueError, match="minimum history days"):
        StrategyDefinition(
            name="momentum",
            display_name="Momentum",
            description="Momentum strategy.",
            supports_backtest=True,
            supports_signal_generation=True,
            minimum_history_days=0,
        )
