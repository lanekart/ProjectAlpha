from __future__ import annotations

from dataclasses import dataclass

from alpha.market.bar import Bar
from alpha.market.bar_series import BarSeries


@dataclass(slots=True)
class SeriesBuilder:
    """
    Converts streaming bars into validated BarSeries.

    Purpose:
    - clean boundary between streaming system and analytical system
    - ensures final dataset invariants are enforced once
    """

    symbol: str | None = None

    def build(self, bars: list[Bar]) -> BarSeries:
        if not bars:
            raise ValueError("cannot build empty BarSeries")

        # enforce symbol consistency at boundary
        symbol = bars[0].symbol

        for b in bars:
            if b.symbol != symbol:
                raise ValueError("mixed symbols in series build")

        return BarSeries(bars)
