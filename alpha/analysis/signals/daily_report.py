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
    analysis: pd.DataFrame


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
        df = _ensure_report_metrics(df)

        top_gainers = _top_gainers(df)
        top_losers = _top_losers(df)

        regime = self._detect_regime(df)

        return {
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "regime": regime,
            "signals": df[["symbol", "alpha_score", "signal"]],
            "analysis": df,
        }

    def _detect_regime(self, df: pd.DataFrame) -> str:
        avg_score = df["alpha_score"].mean()

        if avg_score > 0.01:
            return "risk_on"
        if avg_score < -0.01:
            return "risk_off"
        return "neutral"


def _ensure_report_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preserve the public daily-report output contract while using the
    canonical feature metric produced by FeatureEngine.

    FeatureEngine owns the canonical short-term momentum metric:
    ``momentum_1d``.

    The CLI and earlier report consumers display ``momentum_score``.
    We therefore expose ``momentum_score`` as a report-level alias,
    rather than inventing a second calculation.
    """

    if "momentum_1d" not in df.columns:
        raise ValueError("[DAILY REPORT] momentum_1d not found in input")

    result = df.copy()
    result["momentum_score"] = result["momentum_1d"]

    return result


def _top_gainers(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    return (
        df.loc[df["momentum_score"] > 0]
        .sort_values(
            by=["momentum_score", "symbol"],
            ascending=[False, True],
            kind="mergesort",
        )
        .drop_duplicates(subset=["symbol"], keep="first")
        .head(limit)
    )


def _top_losers(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    gainers = set(_top_gainers(df, limit=limit)["symbol"].astype(str))

    return (
        df.loc[(df["momentum_score"] < 0) & (~df["symbol"].astype(str).isin(gainers))]
        .sort_values(
            by=["momentum_score", "symbol"],
            ascending=[True, True],
            kind="mergesort",
        )
        .drop_duplicates(subset=["symbol"], keep="first")
        .head(limit)
    )
