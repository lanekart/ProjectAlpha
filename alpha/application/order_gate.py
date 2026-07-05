from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alpha.execution.order import Order
from alpha.market.tradability.score_engine import TradabilityScoreEngine


@dataclass
class OrderGate:
    """
    Filters orders before they reach the execution layer.

    This acts as the institutional pre-trade risk filter.
    """

    score_engine: TradabilityScoreEngine
    min_score: float = 60.0

    def allow(
        self,
        order: Order,
        market_context: dict[str, Any],
    ) -> bool:
        """
        Decide whether an order is tradable.
        """

        avg_volume = market_context.get("avg_volume", 0)
        volatility = market_context.get("volatility", 0)

        score = self.score_engine.score(
            avg_volume=avg_volume,
            volatility=volatility,
        )

        # Store diagnostics inside the order metadata rather than
        # attaching dynamic attributes.
        order.metadata["tradability_score"] = score

        return float(score) >= self.min_score
