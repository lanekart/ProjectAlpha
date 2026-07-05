from __future__ import annotations

from typing import TypedDict

import pandas as pd

from alpha.analysis.factors.alpha_model import AlphaModel
from alpha.analysis.features.feature_engine import FeatureEngine
from alpha.analysis.rankings.ranker import Ranker
from alpha.analysis.signals.signal_engine import SignalEngine


class DailyReport(TypedDict):
    top_gainers: pd.DataFrame
    top_losers: pd.DataFrame
    regime: str
    signals: pd.DataFrame


class DailyMarketReport:
    """
    Full market intelligence pipeline.
    """

    def __init__(self) -> None:
        self.features = FeatureEngine()
        self.model = AlphaModel()
        self.ranker = Ranker()
        self.signals = SignalEngine()

    def generate(self, df: pd.DataFrame) -> DailyReport:
        df = self.features.build(df)
        df = self.model.score(df)
        df = self.ranker.rank(df)
        df = self.signals.generate(df)

        top = df.head(10)
        bottom = df.tail(10)

        regime = self._detect_regime(df)

        return {
            "top_gainers": top,
            "top_losers": bottom,
            "regime": regime,
            "signals": df[["symbol", "alpha_score", "signal"]],
        }

    def _detect_regime(self, df: pd.DataFrame) -> str:
        avg_score = df["alpha_score"].mean()

        if avg_score > 0.01:
            return "risk_on"
        elif avg_score < -0.01:
            return "risk_off"
        return "neutral"
