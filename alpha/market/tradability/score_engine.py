from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.market.tradability.liquidity import LiquidityModel
from alpha.market.tradability.volatility import VolatilityModel


@dataclass
class TradabilityScoreEngine:
    """
    Combines market features into a single tradability score.
    """

    liquidity_model: LiquidityModel = LiquidityModel()
    volatility_model: VolatilityModel = VolatilityModel()

    def score(
        self,
        avg_volume: int,
        volatility: Decimal,
    ) -> Decimal:
        liquidity_score = self.liquidity_model.score(avg_volume)
        volatility_score = self.volatility_model.score(volatility)

        # weighted combination (institutional simplification)
        return (liquidity_score * Decimal("0.6")) + (volatility_score * Decimal("0.4"))
