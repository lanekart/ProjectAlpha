from __future__ import annotations

import pandas as pd


class Ranker:
    """
    Ranks stocks by alpha score.
    """

    def rank(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df = df.sort_values("alpha_score", ascending=False)
        df["rank"] = range(1, len(df) + 1)

        return df
