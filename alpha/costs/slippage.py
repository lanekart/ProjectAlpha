from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.costs.model import CostInput


@dataclass(frozen=True, slots=True)
class FixedSlippageModel:
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount < Decimal("0"):
            raise ValueError("slippage amount cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        del cost_input
        return self.amount


@dataclass(frozen=True, slots=True)
class BasisPointSlippageModel:
    basis_points: Decimal

    def __post_init__(self) -> None:
        if self.basis_points < Decimal("0"):
            raise ValueError("basis_points cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        return cost_input.notional * self.basis_points / Decimal("10000")


@dataclass(frozen=True, slots=True)
class PerShareSlippageModel:
    amount_per_share: Decimal

    def __post_init__(self) -> None:
        if self.amount_per_share < Decimal("0"):
            raise ValueError("amount_per_share cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        return abs(Decimal(cost_input.quantity)) * self.amount_per_share
