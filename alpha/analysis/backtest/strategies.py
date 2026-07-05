import numpy as np
import pandas as pd

from alpha.analysis.backtest.config import BacktestConfig


def apply_signal_filter(df: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    df = df.copy()
    return df[df["signal"].isin(["BUY", "SELL"])]


def compute_weights(df: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    df = df.copy()

    df["direction"] = np.where(df["signal"] == "BUY", 1.0, -1.0)

    if config.weighting == "equal":
        df["weight"] = 1.0

    elif config.weighting == "alpha":
        df["weight"] = df["alpha_score"].abs()

    elif config.weighting == "topk":
        k = config.top_k or 10
        df = df.sort_values("alpha_score", ascending=False)
        df = df.groupby("date").head(k)
        df["weight"] = df["alpha_score"].abs()

    return df


def normalize_weights(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def norm(group: pd.DataFrame) -> pd.DataFrame:
        total = group["weight"].sum()
        group["weight"] = group["weight"] / total if total != 0 else 0
        return group

    return df.groupby("date", group_keys=False).apply(norm)
