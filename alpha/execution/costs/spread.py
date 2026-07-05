from __future__ import annotations

from decimal import Decimal


class SpreadModel:
    """
    Adds bid-ask spread cost.
    """

    def apply(self, price: Decimal, spread_bps: Decimal) -> Decimal:
        return price * (Decimal("1") + spread_bps / Decimal("10000"))
