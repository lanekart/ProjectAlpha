from __future__ import annotations

from decimal import Decimal


class SlippageModel:
    """
    Models random execution deviation from expected price.
    """

    def apply(self, price: Decimal, volatility: Decimal) -> Decimal:
        """
        Simple deterministic approximation (no randomness for reproducibility).
        """

        slippage_factor = volatility / Decimal("100")

        return price * (Decimal("1") + slippage_factor)
