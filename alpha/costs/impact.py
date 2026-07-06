from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.costs.model import CostInput


@dataclass(frozen=True, slots=True)
class ParticipationRateImpactModel:
    participation_rate: Decimal
    impact_rate: Decimal

    def __post_init__(self) -> None:
        if self.participation_rate < Decimal("0"):
            raise ValueError("participation_rate cannot be negative")
        if self.impact_rate < Decimal("0"):
            raise ValueError("impact_rate cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        return cost_input.notional * self.participation_rate * self.impact_rate


@dataclass(frozen=True, slots=True)
class SquareRootImpactModel:
    daily_volume: Decimal
    volatility: Decimal
    impact_coefficient: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.daily_volume <= Decimal("0"):
            raise ValueError("daily_volume must be positive")
        if self.volatility < Decimal("0"):
            raise ValueError("volatility cannot be negative")
        if self.impact_coefficient < Decimal("0"):
            raise ValueError("impact_coefficient cannot be negative")

    def calculate(self, cost_input: CostInput) -> Decimal:
        participation = abs(Decimal(cost_input.quantity)) / self.daily_volume
        return (
            cost_input.notional
            * self.impact_coefficient
            * self.volatility
            * participation.sqrt()
        )
