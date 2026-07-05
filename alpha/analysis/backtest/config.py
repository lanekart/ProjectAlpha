from dataclasses import dataclass
from typing import Literal

WeightingMode = Literal["alpha", "equal", "topk"]


@dataclass
class BacktestConfig:
    """
    Controls backtest behavior without changing engine logic.
    """

    weighting: WeightingMode = "alpha"

    top_k: int | None = None

    transaction_cost: float = 0.0

    rebalance: Literal["daily", "weekly"] = "daily"

    long_only: bool = True
