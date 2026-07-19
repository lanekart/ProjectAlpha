from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.strategy_discovery.models import DiscoveryRow
from alpha.strategy_lab.models import (
    ExecutionAssumptionProfile,
    LabStrategySpecification,
    PeriodPerformance,
    RollingPerformance,
    TimeSeriesReport,
)
from alpha.strategy_lab.performance_metrics import PerformanceMetricsEngine

_TWO = Decimal("0.01")


class TimeSeriesAnalysis:
    """Create annual, quarterly, rolling, equity, and underwater evidence."""

    def __init__(self, metrics: PerformanceMetricsEngine | None = None) -> None:
        self.metrics = metrics or PerformanceMetricsEngine()

    def analyze(
        self,
        *,
        strategy: LabStrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        profile: ExecutionAssumptionProfile,
    ) -> TimeSeriesReport:
        selected = tuple(
            item
            for item in self.metrics.selected_rows(strategy, rows)
            if item.realised_return_pct is not None
        )
        annual_groups: dict[str, list[DiscoveryRow]] = defaultdict(list)
        quarter_groups: dict[str, list[DiscoveryRow]] = defaultdict(list)
        for item in selected:
            annual_groups[str(item.candidate_timestamp.year)].append(item)
            quarter = (item.candidate_timestamp.month - 1) // 3 + 1
            quarter_groups[f"{item.candidate_timestamp.year}-Q{quarter}"].append(item)
        annual = tuple(
            self._period(strategy, key, tuple(values), profile)
            for key, values in sorted(annual_groups.items())
        )
        quarterly = tuple(
            self._period(strategy, key, tuple(values), profile)
            for key, values in sorted(quarter_groups.items())
        )
        ordered = tuple(
            sorted(
                selected, key=lambda item: (item.candidate_timestamp, item.candidate_id)
            )
        )
        equity, underwater = _curves(ordered, profile)
        return TimeSeriesReport(
            strategy_id=strategy.strategy_id,
            annual=annual,
            quarterly=quarterly,
            rolling_20=self._rolling(strategy, ordered, profile, 20),
            rolling_50=self._rolling(strategy, ordered, profile, 50),
            equity_curve=equity,
            underwater_curve=underwater,
        )

    def _period(
        self,
        strategy: LabStrategySpecification,
        period: str,
        rows: tuple[DiscoveryRow, ...],
        profile: ExecutionAssumptionProfile,
    ) -> PeriodPerformance:
        metrics = self.metrics.evaluate(strategy=strategy, rows=rows, profile=profile)
        return PeriodPerformance(
            period=period,
            completed_trades=metrics.completed_trades,
            precision_pct=metrics.precision_pct,
            expectancy_pct=metrics.expectancy_pct,
            profit_factor=metrics.profit_factor,
            net_return_pct=metrics.total_return_pct,
            maximum_drawdown_pct=metrics.maximum_drawdown_pct,
        )

    def _rolling(
        self,
        strategy: LabStrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        profile: ExecutionAssumptionProfile,
        window: int,
    ) -> tuple[RollingPerformance, ...]:
        if len(rows) < window:
            return ()
        values: list[RollingPerformance] = []
        for end in range(window, len(rows) + 1):
            sample = rows[end - window : end]
            metrics = self.metrics.evaluate(
                strategy=strategy,
                rows=sample,
                profile=profile,
            )
            values.append(
                RollingPerformance(
                    end_date=sample[-1].candidate_timestamp.date(),
                    window=window,
                    completed_trades=metrics.completed_trades,
                    precision_pct=metrics.precision_pct,
                    expectancy_pct=metrics.expectancy_pct,
                    profit_factor=metrics.profit_factor,
                    drawdown_pct=metrics.maximum_drawdown_pct,
                )
            )
        return tuple(values)


def _curves(
    rows: tuple[DiscoveryRow, ...],
    profile: ExecutionAssumptionProfile,
) -> tuple[
    tuple[tuple[date, Decimal], ...],
    tuple[tuple[date, Decimal], ...],
]:
    equity = Decimal("100000")
    peak = equity
    fraction = profile.capital_per_trade_pct / Decimal("100")
    equity_values: list[tuple[date, Decimal]] = []
    underwater_values: list[tuple[date, Decimal]] = []
    for item in rows:
        if item.realised_return_pct is None:
            continue
        net = item.realised_return_pct - profile.round_trip_cost_pct
        equity *= Decimal("1") + net / Decimal("100") * fraction
        equity = equity.quantize(_TWO, rounding=ROUND_HALF_UP)
        peak = max(peak, equity)
        underwater = ((peak - equity) / peak * Decimal("100")).quantize(
            _TWO, rounding=ROUND_HALF_UP
        )
        day = item.candidate_timestamp.date()
        equity_values.append((day, equity))
        underwater_values.append((day, underwater))
    return tuple(equity_values), tuple(underwater_values)


__all__ = ["TimeSeriesAnalysis"]
