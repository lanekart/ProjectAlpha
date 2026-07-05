from __future__ import annotations

import pandas as pd


class FeatureEngine:
    """
    Computes market features from raw OHLCV data.
    """

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # -------------------------
        # MOMENTUM
        # -------------------------
        df["momentum_1d"] = (df["close"] - df["open"]) / df["open"]

        # -------------------------
        # VOLATILITY (intraday range)
        # -------------------------
        if "high" in df.columns and "low" in df.columns:
            df["volatility"] = (df["high"] - df["low"]) / df["open"]
        else:
            df["volatility"] = 0.0

        # -------------------------
        # LIQUIDITY proxy
        # -------------------------
        if "volume" in df.columns:
            df["liquidity"] = df["volume"]
        else:
            df["liquidity"] = 0.0

        return df
