from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from alpha.market.features.feature_engine import FeatureVector


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class Signal:
    timestamp: str
    signal: SignalType
    strength: Decimal


class SignalEngine:
    def generate(self, features: Sequence[FeatureVector]) -> tuple[Signal, ...]:
        signals: list[Signal] = []

        for feature_vector in features:
            feature_values = feature_vector.features

            signals.append(
                Signal(
                    timestamp=feature_vector.timestamp,
                    signal=self._evaluate(feature_values),
                    strength=self._strength(feature_values),
                )
            )

        return tuple(signals)

    def _evaluate(self, features: dict[str, Decimal]) -> SignalType:
        close = features.get("close", Decimal("0"))
        sma5 = features.get("sma_5")
        sma10 = features.get("sma_10")

        if sma5 is None or sma10 is None:
            return SignalType.HOLD

        if sma5 > sma10 and close > sma5:
            return SignalType.BUY

        if sma5 < sma10 and close < sma5:
            return SignalType.SELL

        return SignalType.HOLD

    def _strength(self, features: dict[str, Decimal]) -> Decimal:
        sma5 = features.get("sma_5")
        sma10 = features.get("sma_10")

        if sma5 is None or sma10 is None:
            return Decimal("0")

        return abs(sma5 - sma10)
