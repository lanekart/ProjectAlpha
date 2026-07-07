from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from alpha.backtest.performance import PerformanceSummary

_ZERO = Decimal("0")
_ONE = Decimal("1")
_DEFAULT_PERIODS_PER_YEAR = Decimal("252")


@dataclass(frozen=True, slots=True)
class StrategyStatistics:
    """Immutable strategy-level statistics derived from performance analytics."""

    recovery_factor: Decimal
    gain_to_pain_ratio: Decimal
    system_quality_number: Decimal
    payoff_ratio: Decimal
    kelly_fraction: Decimal
    risk_of_ruin: Decimal
    consecutive_wins: int
    consecutive_losses: int
    trade_frequency: Decimal
    annual_return: Decimal
    monthly_return: Decimal


@dataclass(frozen=True, slots=True)
class StrategyStatisticsEngine:
    """Pure deterministic strategy statistics engine.

    PerformanceAnalytics owns backtest performance calculations.
    StrategyStatisticsEngine derives strategy-comparison statistics from an
    immutable PerformanceSummary and optional realized trade PnL series.
    """

    periods_per_year: Decimal = _DEFAULT_PERIODS_PER_YEAR
    months_per_year: Decimal = Decimal("12")

    def __post_init__(self) -> None:
        if self.periods_per_year <= _ZERO:
            raise ValueError("periods_per_year must be greater than zero")
        if self.months_per_year <= _ZERO:
            raise ValueError("months_per_year must be greater than zero")

    def summarize(
        self,
        performance: PerformanceSummary,
        *,
        trade_pnls: Sequence[Decimal] = (),
        observed_periods: int = 0,
    ) -> StrategyStatistics:
        normalized_trade_pnls = tuple(trade_pnls)

        return StrategyStatistics(
            recovery_factor=self._recovery_factor(performance),
            gain_to_pain_ratio=self._gain_to_pain_ratio(normalized_trade_pnls),
            system_quality_number=self._system_quality_number(normalized_trade_pnls),
            payoff_ratio=self._payoff_ratio(performance),
            kelly_fraction=self._kelly_fraction(performance),
            risk_of_ruin=self._risk_of_ruin(performance),
            consecutive_wins=self._consecutive_wins(normalized_trade_pnls),
            consecutive_losses=self._consecutive_losses(normalized_trade_pnls),
            trade_frequency=self._trade_frequency(
                trade_count=len(normalized_trade_pnls),
                observed_periods=observed_periods,
            ),
            annual_return=performance.cagr,
            monthly_return=self._monthly_return(performance.cagr),
        )

    def _recovery_factor(self, performance: PerformanceSummary) -> Decimal:
        if performance.maximum_drawdown == _ZERO:
            return _ZERO

        return performance.total_return / abs(performance.maximum_drawdown)

    def _gain_to_pain_ratio(self, trade_pnls: Sequence[Decimal]) -> Decimal:
        gross_profit = sum((pnl for pnl in trade_pnls if pnl > _ZERO), _ZERO)
        gross_loss = abs(sum((pnl for pnl in trade_pnls if pnl < _ZERO), _ZERO))

        if gross_profit == _ZERO and gross_loss == _ZERO:
            return _ZERO
        if gross_loss == _ZERO:
            return gross_profit

        return gross_profit / gross_loss

    def _system_quality_number(self, trade_pnls: Sequence[Decimal]) -> Decimal:
        if len(trade_pnls) < 2:
            return _ZERO

        average_trade = sum(trade_pnls, _ZERO) / Decimal(len(trade_pnls))
        standard_deviation = self._sample_standard_deviation(trade_pnls)

        if standard_deviation == _ZERO:
            return _ZERO

        return (
            average_trade
            / standard_deviation
            * self._decimal_from_float(sqrt(len(trade_pnls)))
        )

    def _payoff_ratio(self, performance: PerformanceSummary) -> Decimal:
        if performance.average_loss == _ZERO:
            return _ZERO

        return performance.average_win / abs(performance.average_loss)

    def _kelly_fraction(self, performance: PerformanceSummary) -> Decimal:
        payoff_ratio = self._payoff_ratio(performance)
        if payoff_ratio == _ZERO:
            return _ZERO

        loss_rate = _ONE - performance.win_rate
        return performance.win_rate - (loss_rate / payoff_ratio)

    def _risk_of_ruin(self, performance: PerformanceSummary) -> Decimal:
        if performance.win_rate <= _ZERO:
            return _ONE
        if performance.win_rate >= _ONE:
            return _ZERO

        loss_rate = _ONE - performance.win_rate
        if performance.win_rate <= loss_rate:
            return _ONE

        edge_ratio = loss_rate / performance.win_rate
        approximation = edge_ratio ** Decimal("10")
        return max(_ZERO, min(_ONE, approximation))

    def _consecutive_wins(self, trade_pnls: Sequence[Decimal]) -> int:
        return self._max_consecutive(trade_pnls=trade_pnls, winning=True)

    def _consecutive_losses(self, trade_pnls: Sequence[Decimal]) -> int:
        return self._max_consecutive(trade_pnls=trade_pnls, winning=False)

    def _max_consecutive(
        self,
        *,
        trade_pnls: Sequence[Decimal],
        winning: bool,
    ) -> int:
        maximum = 0
        current = 0

        for pnl in trade_pnls:
            is_match = pnl > _ZERO if winning else pnl < _ZERO
            if is_match:
                current += 1
                maximum = max(maximum, current)
            else:
                current = 0

        return maximum

    def _trade_frequency(
        self,
        *,
        trade_count: int,
        observed_periods: int,
    ) -> Decimal:
        if trade_count < 0:
            raise ValueError("trade_count cannot be negative")
        if observed_periods < 0:
            raise ValueError("observed_periods cannot be negative")
        if observed_periods == 0:
            return _ZERO

        return Decimal(trade_count) / Decimal(observed_periods) * self.periods_per_year

    def _monthly_return(self, annual_return: Decimal) -> Decimal:
        growth = _ONE + annual_return
        if growth <= _ZERO:
            return Decimal("-1")

        exponent = _ONE / self.months_per_year
        return self._decimal_from_float(float(growth) ** float(exponent) - 1.0)

    def _sample_standard_deviation(self, values: Sequence[Decimal]) -> Decimal:
        if len(values) < 2:
            return _ZERO

        average = sum(values, _ZERO) / Decimal(len(values))
        squared_deviations = sum((value - average) ** 2 for value in values)
        variance = squared_deviations / Decimal(len(values) - 1)
        return self._decimal_from_float(sqrt(float(variance)))

    def _decimal_from_float(self, value: float) -> Decimal:
        return Decimal(str(value))
