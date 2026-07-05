from __future__ import annotations

import pandas as pd


class Backtester:
    """
    Simple daily signal backtester.

    Assumes:
    - Data is already ranked and contains alpha_score + signal
    - Each row is one stock per day
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self.initial_capital = initial_capital

    def run(self, df: pd.DataFrame) -> dict[str, object]:
        """
        Returns backtest results.
        """

        if "signal" not in df.columns:
            raise ValueError("Missing signal column")

        df = df.copy()

        # ensure return column exists
        if "return" not in df.columns:
            df["return"] = df["alpha_score"] * 0.01

        df["strategy_return"] = df.apply(self._apply_signal, axis=1)

        df["equity"] = (1 + df["strategy_return"]).cumprod() * self.initial_capital

        total_return = float(df["equity"].iloc[-1] / self.initial_capital - 1)

        win_rate = float((df["strategy_return"] > 0).mean())

        return {
            "final_equity": float(df["equity"].iloc[-1]),
            "total_return": total_return,
            "win_rate": win_rate,
            "equity_curve": df["equity"],
        }

    def _apply_signal(self, row: pd.Series) -> float:
        signal = str(row["signal"])
        ret = float(row["return"])

        if signal == "BUY":
            return ret
        if signal == "SELL":
            return -ret
        return 0.0
