from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from alpha.market.bar_series import BarSeries
from alpha.market.indicators.core import ema, returns, sma, volatility


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """
    Immutable feature container for a single time index.

    Designed for:
    - strategy consumption
    - ranking models
    - backtesting pipelines
    """

    timestamp: str
    features: dict[str, Decimal]


class FeatureEngine:
    """
    Converts BarSeries into feature vectors.

    Stateless, deterministic, and replay-safe.
    """

    def __init__(self) -> None:
        pass

    # -----------------------------
    # Public API
    # -----------------------------

    def build(self, series: BarSeries) -> Sequence[FeatureVector]:
        closes = [bar.close for bar in series]
        timestamps = [str(bar.timestamp) for bar in series]

        result: list[FeatureVector] = []

        for i in range(len(series)):
            window = closes[: i + 1]

            features: dict[str, Decimal] = {}

            # --- price features ---
            features["close"] = window[-1]

            # --- trend features ---
            if len(window) >= 5:
                features["sma_5"] = sma(window, 5)
            if len(window) >= 10:
                features["sma_10"] = sma(window, 10)

            if len(window) >= 10:
                features["ema_10"] = ema(window, 10)

            # --- momentum ---
            r = returns(window)
            features["return_1"] = r[-1] if r else Decimal("0")

            # --- risk ---
            if len(window) >= 10:
                features["volatility_10"] = volatility(window)

            result.append(
                FeatureVector(
                    timestamp=timestamps[i],
                    features=features,
                )
            )

        return tuple(result)
