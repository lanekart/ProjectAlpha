from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import SignalBatch, SignalSide, TradingSignal


def test_trading_signal_normalizes_public_fields() -> None:
    signal = TradingSignal(
        symbol=" reliance ",
        side=SignalSide.BUY,
        strategy=" Momentum ",
        generated_for=date(2026, 7, 7),
        confidence=Decimal("0.75"),
        reference_price=Decimal("2875.50"),
        reasons=(" positive momentum ",),
    )

    assert signal.symbol == "RELIANCE"
    assert signal.strategy == "momentum"
    assert signal.confidence == Decimal("0.75")
    assert signal.reference_price == Decimal("2875.50")
    assert signal.reasons == ("positive momentum",)
    assert signal.is_actionable is True


def test_trading_signal_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        TradingSignal(
            symbol="RELIANCE",
            side=SignalSide.BUY,
            strategy="momentum",
            generated_for=date(2026, 7, 7),
            confidence=Decimal("1.01"),
        )


def test_signal_batch_is_deterministically_sorted_and_grouped() -> None:
    generated_for = date(2026, 7, 7)
    batch = SignalBatch.from_iterable(
        strategy="momentum",
        generated_for=generated_for,
        signals=(
            TradingSignal(
                symbol="TCS",
                side=SignalSide.SELL,
                strategy="momentum",
                generated_for=generated_for,
            ),
            TradingSignal(
                symbol="RELIANCE",
                side=SignalSide.BUY,
                strategy="momentum",
                generated_for=generated_for,
            ),
            TradingSignal(
                symbol="INFY",
                side=SignalSide.HOLD,
                strategy="momentum",
                generated_for=generated_for,
            ),
        ),
    )

    assert tuple(signal.symbol for signal in batch.signals) == (
        "INFY",
        "RELIANCE",
        "TCS",
    )
    assert tuple(signal.symbol for signal in batch.buys) == ("RELIANCE",)
    assert tuple(signal.symbol for signal in batch.sells) == ("TCS",)
    assert tuple(signal.symbol for signal in batch.holds) == ("INFY",)
    assert tuple(signal.symbol for signal in batch.actionable) == ("RELIANCE", "TCS")


def test_signal_batch_rejects_mismatched_strategy() -> None:
    generated_for = date(2026, 7, 7)

    with pytest.raises(ValueError, match="strategy"):
        SignalBatch(
            strategy="momentum",
            generated_for=generated_for,
            signals=(
                TradingSignal(
                    symbol="RELIANCE",
                    side=SignalSide.BUY,
                    strategy="mean_reversion",
                    generated_for=generated_for,
                ),
            ),
        )
