from __future__ import annotations

import pandas as pd


class AlphaModel:
    """
    Combines features into a single alpha score.
    """

    def __init__(
        self,
        w_momentum: float = 0.5,
        w_liquidity: float = 0.3,
        w_volatility: float = 0.2,
    ) -> None:
        self.w_momentum = w_momentum
        self.w_liquidity = w_liquidity
        self.w_volatility = w_volatility

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["alpha_score"] = (
            self.w_momentum * df["momentum_1d"]
            + self.w_liquidity * (df["liquidity"] / df["liquidity"].max())
            - self.w_volatility * df["volatility"]
        )

        return df
