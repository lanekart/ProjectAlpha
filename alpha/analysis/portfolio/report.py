from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PortfolioAnalyticsReport:
    """
    Immutable analytics report derived from a portfolio snapshot.
    """

    cash: Decimal
    market_value: Decimal
    total_equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    cash_weight: Decimal
    gross_exposure_weight: Decimal
    net_exposure_weight: Decimal
    position_count: int
    long_count: int
    short_count: int
    largest_position_symbol: str | None
    largest_position_weight: Decimal
