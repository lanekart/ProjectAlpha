from __future__ import annotations

from decimal import Decimal


class VolatilityModel:
    """
    Penalizes high volatility assets.

    Higher volatility → lower score.
    """

    def score(self, volatility: Decimal) -> Decimal:
        if volatility <= Decimal("1"):
            return Decimal("100")

        if volatility <= Decimal("2"):
            return Decimal("80")

        if volatility <= Decimal("4"):
            return Decimal("50")

        if volatility <= Decimal("8"):
            return Decimal("20")

        return Decimal("0")
