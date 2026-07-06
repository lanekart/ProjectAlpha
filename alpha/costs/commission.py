from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.costs.model import CostInput


@dataclass(frozen=True, slots=True)
class FixedCommissionModel:
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount < Decimal("0"):
            raise ValueError("commission amount cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        del cost_input
        return self.amount


@dataclass(frozen=True, slots=True)
class PercentageCommissionModel:
    rate: Decimal

    def __post_init__(self) -> None:
        if self.rate < Decimal("0"):
            raise ValueError("commission rate cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        return cost_input.notional * self.rate
