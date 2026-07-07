from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

_ZERO = Decimal("0")
_ONE = Decimal("1")


class SignalSide(StrEnum):
    """Canonical deterministic trading signal side."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class TradingSignal:
    """Immutable application-facing trading signal.

    This object is intentionally small and deterministic. It is suitable for
    report generation, CLI output, paper-trading audit trails, and future
    recommendation workflows.
    """

    symbol: str
    side: SignalSide
    strategy: str
    generated_for: date
    confidence: Decimal = _ONE
    reference_price: Decimal | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        normalized_strategy = self.strategy.strip().lower()
        normalized_confidence = Decimal(str(self.confidence))

        if not normalized_symbol:
            raise ValueError("signal symbol cannot be empty")
        if not normalized_strategy:
            raise ValueError("signal strategy cannot be empty")
        if normalized_confidence < _ZERO or normalized_confidence > _ONE:
            raise ValueError("signal confidence must be between 0 and 1")

        normalized_price = self.reference_price
        if normalized_price is not None:
            normalized_price = Decimal(str(normalized_price))
            if normalized_price <= _ZERO:
                raise ValueError("signal reference price must be positive")

        normalized_reasons = tuple(reason.strip() for reason in self.reasons)
        if any(not reason for reason in normalized_reasons):
            raise ValueError("signal reasons cannot contain empty values")

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(self, "confidence", normalized_confidence)
        object.__setattr__(self, "reference_price", normalized_price)
        object.__setattr__(self, "reasons", normalized_reasons)

    @property
    def is_actionable(self) -> bool:
        """Return whether the signal represents a tradeable action."""

        return self.side in {SignalSide.BUY, SignalSide.SELL}


@dataclass(frozen=True, slots=True)
class SignalBatch:
    """Immutable deterministic collection of trading signals."""

    strategy: str
    generated_for: date
    signals: tuple[TradingSignal, ...]

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("signal batch strategy cannot be empty")

        sorted_signals = tuple(
            sorted(
                self.signals,
                key=lambda signal: (
                    signal.symbol,
                    signal.side.value,
                    signal.confidence,
                ),
            )
        )

        for signal in sorted_signals:
            if signal.strategy != normalized_strategy:
                raise ValueError("signal strategy must match batch strategy")
            if signal.generated_for != self.generated_for:
                raise ValueError("signal date must match batch date")

        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(self, "signals", sorted_signals)

    @classmethod
    def from_iterable(
        cls,
        *,
        strategy: str,
        generated_for: date,
        signals: Iterable[TradingSignal],
    ) -> SignalBatch:
        """Build a deterministic batch from any signal iterable."""

        return cls(
            strategy=strategy,
            generated_for=generated_for,
            signals=tuple(signals),
        )

    @property
    def buys(self) -> tuple[TradingSignal, ...]:
        return tuple(signal for signal in self.signals if signal.side is SignalSide.BUY)

    @property
    def sells(self) -> tuple[TradingSignal, ...]:
        return tuple(
            signal for signal in self.signals if signal.side is SignalSide.SELL
        )

    @property
    def holds(self) -> tuple[TradingSignal, ...]:
        return tuple(
            signal for signal in self.signals if signal.side is SignalSide.HOLD
        )

    @property
    def actionable(self) -> tuple[TradingSignal, ...]:
        return tuple(signal for signal in self.signals if signal.is_actionable)
