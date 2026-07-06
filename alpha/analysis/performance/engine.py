from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.analysis.performance.report import PerformanceReport
from alpha.portfolio.equity_curve import EquityCurve


@dataclass(frozen=True, slots=True)
class PerformanceEngine:
    """
    Computes immutable performance analytics from an equity curve.
    """

    annualization_factor: Decimal = Decimal("252")

    def analyze(self, equity_curve: EquityCurve) -> PerformanceReport:
        returns = equity_curve.returns

        average_return = self._average(returns)
        volatility = self._standard_deviation(returns)
        downside_volatility = self._downside_deviation(returns)

        annualized_volatility = volatility * self.annualization_factor.sqrt()
        annualized_downside_volatility = (
            downside_volatility * self.annualization_factor.sqrt()
        )

        sharpe = self._safe_divide(
            average_return * self.annualization_factor,
            annualized_volatility,
        )

        sortino = self._safe_divide(
            average_return * self.annualization_factor,
            annualized_downside_volatility,
        )

        max_drawdown = equity_curve.max_drawdown

        calmar = self._safe_divide(
            equity_curve.total_return,
            abs(max_drawdown),
        )

        return PerformanceReport(
            total_return=equity_curve.total_return,
            volatility=annualized_volatility,
            downside_volatility=annualized_downside_volatility,
            sharpe=sharpe,
            sortino=sortino,
            max_drawdown=max_drawdown,
            calmar=calmar,
            average_return=average_return,
            best_return=max(returns),
            worst_return=min(returns),
            observations=len(returns),
        )

    def _average(self, values: tuple[Decimal, ...]) -> Decimal:
        if not values:
            return Decimal("0")

        return sum(values, Decimal("0")) / Decimal(len(values))

    def _standard_deviation(self, values: tuple[Decimal, ...]) -> Decimal:
        if len(values) < 2:
            return Decimal("0")

        average = self._average(values)

        variance = sum(
            ((value - average) ** Decimal("2") for value in values),
            Decimal("0"),
        ) / Decimal(len(values))

        return variance.sqrt()

    def _downside_deviation(self, values: tuple[Decimal, ...]) -> Decimal:
        downside = tuple(value for value in values if value < Decimal("0"))

        if len(downside) < 2:
            return Decimal("0")

        return self._standard_deviation(downside)

    def _safe_divide(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == Decimal("0"):
            return Decimal("0")

        return numerator / denominator
