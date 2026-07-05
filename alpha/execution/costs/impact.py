from __future__ import annotations

from decimal import Decimal


class MarketImpactModel:
    """
    Simulates liquidity-based price impact.
    """

    def apply(self, price: Decimal, order_size: int, avg_volume: int) -> Decimal:
        if avg_volume == 0:
            return price * Decimal("1.02")

        impact = Decimal(order_size) / Decimal(avg_volume)

        return price * (Decimal("1") + impact)
