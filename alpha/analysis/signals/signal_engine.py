from __future__ import annotations

import pandas as pd


class SignalEngine:
    """
    Converts ranked alpha scores into trading signals.
    """

    def __init__(
        self,
        buy_threshold: float = 0.02,
        sell_threshold: float = -0.02,
    ) -> None:
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds a `signal` column to the dataframe.

        Signals:
        - BUY
        - SELL
        - HOLD
        """

        df = df.copy()

        if "alpha_score" not in df.columns:
            raise ValueError("alpha_score column missing from dataframe")

        def _signal(score: float) -> str:
            if score >= self.buy_threshold:
                return "BUY"
            if score <= self.sell_threshold:
                return "SELL"
            return "HOLD"

        df["signal"] = df["alpha_score"].apply(_signal)

        return df
