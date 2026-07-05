from __future__ import annotations

import numpy as np
import pandas as pd

from alpha.analysis.backtest.config import BacktestConfig
from alpha.analysis.backtest.strategies import (
    apply_signal_filter,
    compute_weights,
    normalize_weights,
)


class PortfolioBacktester:
    """
    Config-driven portfolio backtesting engine.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self.initial_capital = initial_capital

    def run(self, df: pd.DataFrame, config: BacktestConfig) -> dict[str, object]:
        df = df.copy()

        df["date"] = pd.to_datetime(df["date"])

        if "return" not in df.columns:
            df["return"] = df["alpha_score"] * 0.01

        df = apply_signal_filter(df, config)
        df = compute_weights(df, config)
        df = normalize_weights(df)

        df["strategy_return"] = df["weight"] * df["direction"] * df["return"]

        daily_returns = df.groupby("date")["strategy_return"].sum().sort_index()

        equity = (1 + daily_returns).cumprod() * self.initial_capital

        total_return = float(equity.iloc[-1] / self.initial_capital - 1)

        volatility = float(daily_returns.std() * np.sqrt(252))

        sharpe = float(
            (daily_returns.mean() / (daily_returns.std() + 1e-9)) * np.sqrt(252)
        )

        drawdown = (equity - equity.cummax()) / equity.cummax()

        return {
            "equity_curve": equity,
            "daily_returns": daily_returns,
            "total_return": total_return,
            "sharpe": sharpe,
            "volatility": volatility,
            "max_drawdown": float(drawdown.min()),
        }
