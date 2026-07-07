from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import (
    MomentumSignalAdapter,
    SignalSide,
    StrategyAdapterRegistry,
    default_strategy_adapter_registry,
)


def test_momentum_adapter_generates_deterministic_signal_batch() -> None:
    adapter = MomentumSignalAdapter()

    batch = adapter.generate(
        records=(
            {
                "symbol": "tcs",
                "signal": "BUY",
                "close": "3900.50",
                "confidence": "0.80",
            },
            {
                "symbol": "infy",
                "signal": "SELL",
                "close": "1500.25",
            },
        ),
        generated_for=date(2026, 7, 7),
    )

    assert batch.strategy == "momentum"
    assert batch.generated_for == date(2026, 7, 7)
    assert tuple(signal.symbol for signal in batch.signals) == ("INFY", "TCS")
    assert tuple(signal.side for signal in batch.signals) == (
        SignalSide.SELL,
        SignalSide.BUY,
    )
    assert batch.signals[1].reference_price == Decimal("3900.50")
    assert batch.signals[1].confidence == Decimal("0.80")


def test_momentum_adapter_clamps_confidence() -> None:
    adapter = MomentumSignalAdapter()

    batch = adapter.generate(
        records=(
            {
                "symbol": "RELIANCE",
                "signal": "BUY",
                "confidence": "2.5",
            },
        ),
        generated_for=date(2026, 7, 7),
    )

    assert batch.signals[0].confidence == Decimal("1")


def test_momentum_adapter_rejects_unknown_signal_side() -> None:
    adapter = MomentumSignalAdapter()

    with pytest.raises(ValueError, match="unsupported signal side"):
        adapter.generate(
            records=(
                {
                    "symbol": "TCS",
                    "signal": "WATCH",
                },
            ),
            generated_for=date(2026, 7, 7),
        )


def test_strategy_adapter_registry_is_deterministic() -> None:
    registry = StrategyAdapterRegistry((MomentumSignalAdapter(),))

    assert len(registry) == 1
    assert "momentum" in registry
    assert registry.names == ("momentum",)
    assert registry.get("MOMENTUM").strategy_name == "momentum"


def test_default_strategy_adapter_registry_contains_momentum() -> None:
    registry = default_strategy_adapter_registry()

    assert registry.names == ("momentum",)
    assert isinstance(registry.get("momentum"), MomentumSignalAdapter)
