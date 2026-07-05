from __future__ import annotations

from decimal import Decimal


class LiquidityModel:
    """
    Simplified liquidity scoring model.

    Higher volume → higher tradability score.
    """

    def score(self, avg_volume: int) -> Decimal:
        if avg_volume <= 0:
            return Decimal("0")

        if avg_volume < 1000:
            return Decimal("20")

        if avg_volume < 10000:
            return Decimal("50")

        if avg_volume < 100000:
            return Decimal("80")

        return Decimal("100")
