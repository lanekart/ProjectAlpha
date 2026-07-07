from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from alpha.backtest.accounting import EquityCurvePoint
from alpha.backtest.models import BacktestResult, BacktestTrade

_ZERO = Decimal("0")
_ONE = Decimal("1")
_DEFAULT_PERIODS_PER_YEAR = Decimal("252")


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Immutable performance summary derived from a deterministic backtest result."""

    total_return: Decimal
    cagr: Decimal
    volatility: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    maximum_drawdown: Decimal
    win_rate: Decimal
    profit_factor: Decimal
    average_win: Decimal
    average_loss: Decimal
    expectancy: Decimal
    exposure: Decimal
    ending_equity: Decimal
    cash_balance: Decimal


@dataclass(frozen=True, slots=True)
class _RealizedTradeStats:
    wins: tuple[Decimal, ...]
    losses: tuple[Decimal, ...]

    @property
    def closed_trade_count(self) -> int:
        return len(self.wins) + len(self.losses)


@dataclass(frozen=True, slots=True)
class PerformanceAnalytics:
    """Pure analytics engine for BacktestResult.

    The deterministic BacktestEngine remains responsible only for execution.
    This class derives performance metrics from immutable inputs without mutating
    the result, trades, positions, or cash balances.

    If an explicit equity_curve is supplied, it remains authoritative for
    backward compatibility. Otherwise, the enriched BacktestResult.equity_curve
    is used when available. Legacy results without an embedded curve still fall
    back to the original two-point starting/ending equity curve.
    """

    periods_per_year: Decimal = _DEFAULT_PERIODS_PER_YEAR
    risk_free_rate: Decimal = _ZERO

    def __post_init__(self) -> None:
        if self.periods_per_year <= _ZERO:
            raise ValueError("periods_per_year must be greater than zero")

    def summarize(
        self,
        result: BacktestResult,
        *,
        equity_curve: Sequence[Decimal] | None = None,
    ) -> PerformanceSummary:
        curve = self._normalized_equity_curve(
            result=result,
            equity_curve=equity_curve,
        )
        returns = self._period_returns(curve)

        total_return = self._total_return(
            starting_equity=result.starting_cash,
            ending_equity=result.equity,
        )
        cagr = self._cagr(total_return=total_return, periods=max(len(curve) - 1, 1))
        volatility = self._annualized_volatility(returns)
        sharpe_ratio = self._sharpe_ratio(returns=returns, volatility=volatility)
        downside_volatility = self._annualized_downside_volatility(returns)
        sortino_ratio = self._sortino_ratio(
            returns=returns,
            downside_volatility=downside_volatility,
        )
        maximum_drawdown = self._maximum_drawdown(curve)
        calmar_ratio = self._calmar_ratio(
            cagr=cagr,
            maximum_drawdown=maximum_drawdown,
        )
        realized_stats = self._realized_trade_stats(result.trades)

        average_win = self._average(realized_stats.wins)
        average_loss = self._average(realized_stats.losses)
        win_rate = self._win_rate(realized_stats)
        profit_factor = self._profit_factor(realized_stats)
        expectancy = self._expectancy(realized_stats)

        return PerformanceSummary(
            total_return=total_return,
            cagr=cagr,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            maximum_drawdown=maximum_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_win=average_win,
            average_loss=average_loss,
            expectancy=expectancy,
            exposure=self._exposure(result),
            ending_equity=result.equity,
            cash_balance=result.ending_cash,
        )

    def _normalized_equity_curve(
        self,
        *,
        result: BacktestResult,
        equity_curve: Sequence[Decimal] | None,
    ) -> tuple[Decimal, ...]:
        curve: tuple[Decimal, ...]

        if equity_curve is not None:
            curve = tuple(equity_curve)
        elif result.equity_curve:
            curve = self._curve_from_result(result.equity_curve)
        else:
            curve = (
                result.starting_cash,
                result.equity,
            )

        if not curve:
            raise ValueError("equity_curve cannot be empty")

        for value in curve:
            if value <= _ZERO:
                raise ValueError("equity_curve values must be greater than zero")

        if curve[0] != result.starting_cash:
            curve = (result.starting_cash, *curve)

        if curve[-1] != result.equity:
            curve = (*curve, result.equity)

        return curve

    def _curve_from_result(
        self,
        equity_curve: Sequence[EquityCurvePoint],
    ) -> tuple[Decimal, ...]:
        return tuple(point.equity for point in equity_curve)

    def _period_returns(self, equity_curve: Sequence[Decimal]) -> tuple[Decimal, ...]:
        returns: list[Decimal] = []

        previous = equity_curve[0]
        for current in equity_curve[1:]:
            returns.append((current - previous) / previous)
            previous = current

        return tuple(returns)

    def _total_return(
        self,
        *,
        starting_equity: Decimal,
        ending_equity: Decimal,
    ) -> Decimal:
        if starting_equity <= _ZERO:
            raise ValueError("starting equity must be greater than zero")
        return (ending_equity - starting_equity) / starting_equity

    def _cagr(self, *, total_return: Decimal, periods: int) -> Decimal:
        if periods <= 0:
            return _ZERO

        growth = _ONE + total_return
        if growth <= _ZERO:
            return Decimal("-1")

        exponent = float(self.periods_per_year / Decimal(periods))
        return self._decimal_from_float(float(growth) ** exponent - 1.0)

    def _annualized_volatility(self, returns: Sequence[Decimal]) -> Decimal:
        if len(returns) < 2:
            return _ZERO

        period_volatility = self._sample_standard_deviation(returns)
        annualization_factor = self._decimal_from_float(
            sqrt(float(self.periods_per_year))
        )
        return period_volatility * annualization_factor

    def _annualized_downside_volatility(self, returns: Sequence[Decimal]) -> Decimal:
        downside_returns = tuple(value for value in returns if value < _ZERO)
        if len(downside_returns) < 2:
            return _ZERO

        period_volatility = self._sample_standard_deviation(downside_returns)
        annualization_factor = self._decimal_from_float(
            sqrt(float(self.periods_per_year))
        )
        return period_volatility * annualization_factor

    def _sample_standard_deviation(self, values: Sequence[Decimal]) -> Decimal:
        if len(values) < 2:
            return _ZERO

        mean = self._average(values)
        squared_deviations = sum((value - mean) ** 2 for value in values)
        variance = squared_deviations / Decimal(len(values) - 1)
        return self._decimal_from_float(sqrt(float(variance)))

    def _sharpe_ratio(
        self,
        *,
        returns: Sequence[Decimal],
        volatility: Decimal,
    ) -> Decimal:
        if volatility == _ZERO:
            return _ZERO

        annualized_return = self._average(returns) * self.periods_per_year
        return (annualized_return - self.risk_free_rate) / volatility

    def _sortino_ratio(
        self,
        *,
        returns: Sequence[Decimal],
        downside_volatility: Decimal,
    ) -> Decimal:
        if downside_volatility == _ZERO:
            return _ZERO

        annualized_return = self._average(returns) * self.periods_per_year
        return (annualized_return - self.risk_free_rate) / downside_volatility

    def _maximum_drawdown(self, equity_curve: Sequence[Decimal]) -> Decimal:
        peak = equity_curve[0]
        maximum_drawdown = _ZERO

        for equity in equity_curve:
            if equity > peak:
                peak = equity

            drawdown = (equity - peak) / peak
            if drawdown < maximum_drawdown:
                maximum_drawdown = drawdown

        return maximum_drawdown

    def _calmar_ratio(self, *, cagr: Decimal, maximum_drawdown: Decimal) -> Decimal:
        if maximum_drawdown == _ZERO:
            return _ZERO
        return cagr / abs(maximum_drawdown)

    def _realized_trade_stats(
        self,
        trades: Sequence[BacktestTrade],
    ) -> _RealizedTradeStats:
        quantities: dict[str, int] = {}
        average_costs: dict[str, Decimal] = {}
        wins: list[Decimal] = []
        losses: list[Decimal] = []

        for trade in trades:
            current_quantity = quantities.get(trade.symbol, 0)
            current_average_cost = average_costs.get(trade.symbol, _ZERO)

            if trade.quantity > 0:
                new_quantity = current_quantity + trade.quantity
                new_cost = (
                    (current_average_cost * Decimal(current_quantity)) + trade.notional
                ) / Decimal(new_quantity)
                quantities[trade.symbol] = new_quantity
                average_costs[trade.symbol] = new_cost
                continue

            sell_quantity = abs(trade.quantity)
            if current_quantity <= 0:
                continue

            closed_quantity = min(sell_quantity, current_quantity)
            pnl = (trade.price - current_average_cost) * Decimal(closed_quantity)

            if pnl > _ZERO:
                wins.append(pnl)
            elif pnl < _ZERO:
                losses.append(pnl)

            remaining_quantity = current_quantity - closed_quantity
            if remaining_quantity > 0:
                quantities[trade.symbol] = remaining_quantity
                average_costs[trade.symbol] = current_average_cost
            else:
                quantities.pop(trade.symbol, None)
                average_costs.pop(trade.symbol, None)

        return _RealizedTradeStats(wins=tuple(wins), losses=tuple(losses))

    def _win_rate(self, stats: _RealizedTradeStats) -> Decimal:
        if stats.closed_trade_count == 0:
            return _ZERO
        return Decimal(len(stats.wins)) / Decimal(stats.closed_trade_count)

    def _profit_factor(self, stats: _RealizedTradeStats) -> Decimal:
        gross_profit = sum(stats.wins, _ZERO)
        gross_loss = abs(sum(stats.losses, _ZERO))

        if gross_profit == _ZERO and gross_loss == _ZERO:
            return _ZERO
        if gross_loss == _ZERO:
            return gross_profit

        return gross_profit / gross_loss

    def _expectancy(self, stats: _RealizedTradeStats) -> Decimal:
        if stats.closed_trade_count == 0:
            return _ZERO

        total_pnl = sum(stats.wins, _ZERO) + sum(stats.losses, _ZERO)
        return total_pnl / Decimal(stats.closed_trade_count)

    def _exposure(self, result: BacktestResult) -> Decimal:
        if result.equity <= _ZERO:
            return _ZERO

        invested_value = result.equity - result.ending_cash
        if invested_value <= _ZERO:
            return _ZERO

        return invested_value / result.equity

    def _average(self, values: Iterable[Decimal]) -> Decimal:
        values_tuple = tuple(values)
        if not values_tuple:
            return _ZERO

        return sum(values_tuple, _ZERO) / Decimal(len(values_tuple))

    def _decimal_from_float(self, value: float) -> Decimal:
        return Decimal(str(value))
