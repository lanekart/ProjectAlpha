from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.costs.model import CostInput


@dataclass(frozen=True, slots=True)
class PercentageTaxModel:
    rate: Decimal
    applies_to_buys: bool = True
    applies_to_sells: bool = True

    def __post_init__(self) -> None:
        if self.rate < Decimal("0"):
            raise ValueError("tax rate cannot be negative")
        if not self.applies_to_buys and not self.applies_to_sells:
            raise ValueError("tax model must apply to buys or sells")

    def calculate(self, cost_input: CostInput) -> Decimal:
        if cost_input.quantity > 0 and not self.applies_to_buys:
            return Decimal("0")
        if cost_input.quantity < 0 and not self.applies_to_sells:
            return Decimal("0")

        return cost_input.notional * self.rate


@dataclass(frozen=True, slots=True)
class FlatFeeModel:
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount < Decimal("0"):
            raise ValueError("fee amount cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        del cost_input
        return self.amount


@dataclass(frozen=True, slots=True)
class CappedPercentageFeeModel:
    rate: Decimal
    cap: Decimal

    def __post_init__(self) -> None:
        if self.rate < Decimal("0"):
            raise ValueError("fee rate cannot be negative")
        if self.cap < Decimal("0"):
            raise ValueError("fee cap cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        return min(cost_input.notional * self.rate, self.cap)
