from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CostInput:
    symbol: str
    quantity: int
    price: Decimal

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.quantity == 0:
            raise ValueError("quantity cannot be zero")
        if self.price <= Decimal("0"):
            raise ValueError("price must be positive")

    @property
    def notional(self) -> Decimal:
        return abs(Decimal(self.quantity)) * self.price


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    market_impact: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for value in (
            self.commission,
            self.slippage,
            self.market_impact,
            self.taxes,
            self.fees,
        ):
            if value < Decimal("0"):
                raise ValueError("cost values cannot be negative")

    @property
    def total(self) -> Decimal:
        return (
            self.commission
            + self.slippage
            + self.market_impact
            + self.taxes
            + self.fees
        )
