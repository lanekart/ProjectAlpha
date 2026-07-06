from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """
    Immutable performance analytics report.
    """

    total_return: Decimal
    volatility: Decimal
    downside_volatility: Decimal
    sharpe: Decimal
    sortino: Decimal
    max_drawdown: Decimal
    calmar: Decimal
    average_return: Decimal
    best_return: Decimal
    worst_return: Decimal
    observations: int
