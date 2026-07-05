import numpy as np
import pandas as pd


class MomentumRanker:
    """
    Ranks stocks based on daily momentum + liquidity.
    """

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # ensure numeric safety
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

        # 1. Price return
        df["return"] = (df["close"] - df["open"]) / df["open"]

        # 2. Liquidity score (log volume)
        df["liq_score"] = np.log1p(df["volume"])

        # 3. Composite momentum score
        df["momentum_score"] = df["return"] + 0.1 * df["liq_score"]

        return df

    def rank(self, df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
        scored = self.compute(df)

        ranked = scored.sort_values("momentum_score", ascending=False)

        return ranked.head(top_n)[["symbol", "momentum_score", "return", "volume"]]
