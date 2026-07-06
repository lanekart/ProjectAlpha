from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """
    High-level trading intent generated from signals.

    This is NOT an execution order.
    It is a portfolio-level decision.
    """

    symbol: str
    side: OrderSide
    quantity: int
    confidence: Decimal
