from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.analysis.execution.report import ExecutionAnalyticsReport
from alpha.execution.fill import Fill


@dataclass(frozen=True, slots=True)
class ExecutionAnalyticsEngine:
    """
    Computes immutable analytics from execution fills.
    """

    def analyze(self, fills: tuple[Fill, ...]) -> ExecutionAnalyticsReport:
        if not fills:
            return ExecutionAnalyticsReport(
                fill_count=0,
                symbol_count=0,
                total_quantity=0,
                gross_turnover=Decimal("0"),
                average_fill_price=Decimal("0"),
                total_commission=Decimal("0"),
                total_slippage=Decimal("0"),
                symbols=(),
            )

        total_quantity = sum(fill.quantity for fill in fills)

        gross_turnover = sum(
            (fill.price * Decimal(abs(fill.quantity)) for fill in fills),
            Decimal("0"),
        )

        total_commission = sum(
            (fill.commission for fill in fills),
            Decimal("0"),
        )

        total_slippage = sum(
            (fill.slippage for fill in fills),
            Decimal("0"),
        )

        average_fill_price = (
            gross_turnover / Decimal(abs(total_quantity))
            if total_quantity != 0
            else Decimal("0")
        )

        symbols = tuple(sorted({fill.symbol for fill in fills}))

        return ExecutionAnalyticsReport(
            fill_count=len(fills),
            symbol_count=len(symbols),
            total_quantity=total_quantity,
            gross_turnover=gross_turnover,
            average_fill_price=average_fill_price,
            total_commission=total_commission,
            total_slippage=total_slippage,
            symbols=symbols,
        )
