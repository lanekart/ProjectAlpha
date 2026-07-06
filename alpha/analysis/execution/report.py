from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ExecutionAnalyticsReport:
    """
    Immutable analytics report derived from execution fills.
    """

    fill_count: int
    symbol_count: int
    total_quantity: int
    gross_turnover: Decimal
    average_fill_price: Decimal
    total_commission: Decimal
    total_slippage: Decimal
    symbols: tuple[str, ...]
