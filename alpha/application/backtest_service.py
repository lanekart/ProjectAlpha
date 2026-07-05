from __future__ import annotations

import pandas as pd

from alpha.analysis.backtest.config import BacktestConfig
from alpha.analysis.backtest.portfolio_backtester import PortfolioBacktester
from alpha.analysis.factors.alpha_model import AlphaModel
from alpha.analysis.features.feature_engine import FeatureEngine
from alpha.analysis.signals.signal_engine import SignalEngine


class BacktestService:
    """
    Runs the complete quantitative pipeline from raw data to
    portfolio performance.
    """

    def __init__(self) -> None:
        self.features = FeatureEngine()
        self.alpha = AlphaModel()
        self.signals = SignalEngine()
        self.backtester = PortfolioBacktester()

    def run(
        self,
        df: pd.DataFrame,
        config: BacktestConfig,
    ) -> dict[str, object]:
        """
        Execute the full research pipeline.
        """

        df = self.features.build(df)
        df = self.alpha.score(df)
        df = self.signals.generate(df)

        return self.backtester.run(df, config)
