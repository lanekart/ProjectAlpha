from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from alpha.costs.model import CostBreakdown, CostInput


class CostComponentModel(Protocol):
    def calculate(self, cost_input: CostInput) -> Decimal:
        """Calculate one cost component."""


@dataclass(frozen=True, slots=True)
class TransactionCostEstimator:
    commission_model: CostComponentModel | None = None
    slippage_model: CostComponentModel | None = None
    market_impact_model: CostComponentModel | None = None
    tax_model: CostComponentModel | None = None
    fee_model: CostComponentModel | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def estimate(self, cost_input: CostInput) -> CostBreakdown:
        return CostBreakdown(
            commission=self._calculate(self.commission_model, cost_input),
            slippage=self._calculate(self.slippage_model, cost_input),
            market_impact=self._calculate(self.market_impact_model, cost_input),
            taxes=self._calculate(self.tax_model, cost_input),
            fees=self._calculate(self.fee_model, cost_input),
        )

    def _calculate(
        self,
        model: CostComponentModel | None,
        cost_input: CostInput,
    ) -> Decimal:
        if model is None:
            return Decimal("0")

        value = model.calculate(cost_input)
        if value < Decimal("0"):
            raise ValueError("cost component cannot be negative")
        return value
