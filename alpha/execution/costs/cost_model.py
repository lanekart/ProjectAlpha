from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CostModel:
    commission_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")

    def compute_commission(self, notional: Decimal) -> Decimal:
        return notional * self.commission_bps / Decimal("10000")

    def compute_slippage(self, notional: Decimal) -> Decimal:
        return notional * self.slippage_bps / Decimal("10000")
