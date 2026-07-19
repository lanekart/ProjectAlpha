from __future__ import annotations

import math
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from alpha.benchmark_replay.models import (
    CapitalCurveRecord,
    IdleCapitalRecord,
    PeriodReturn,
    PortfolioStatistics,
    TradeRecord,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_TRADING_DAYS = Decimal("252")


def portfolio_statistics(
    *,
    starting_capital: Decimal,
    capital_curve: tuple[CapitalCurveRecord, ...],
    trades: tuple[TradeRecord, ...],
    turnover: Decimal,
) -> PortfolioStatistics:
    ending = capital_curve[-1].portfolio_value if capital_curve else starting_capital
    winners = tuple(item for item in trades if item.net_profit_loss > 0)
    losers = tuple(item for item in trades if item.net_profit_loss < 0)
    breakeven = tuple(item for item in trades if item.net_profit_loss == 0)
    gross_profit = sum((item.net_profit_loss for item in winners), _ZERO)
    gross_loss = abs(sum((item.net_profit_loss for item in losers), _ZERO))
    returns = tuple(item.net_return_percent for item in trades)
    daily = tuple(item.daily_return_percent / 100 for item in capital_curve[1:])
    downside = tuple(value for value in daily if value < 0)
    years = _years(capital_curve)
    cagr = (
        _ZERO
        if years <= 0 or starting_capital <= 0
        else _decimal_power(ending / starting_capital, Decimal("1") / years)
        - Decimal("1")
    ) * 100
    volatility = _std(daily) * _sqrt(_TRADING_DAYS) * 100
    sharpe = _annualized_ratio(daily, daily)
    sortino = _annualized_ratio(daily, downside)
    drawdowns = tuple(abs(item.drawdown_percent) for item in capital_curve)
    maximum_drawdown = max(drawdowns, default=_ZERO)
    ulcer = _sqrt(_mean(tuple(value * value for value in drawdowns)) or _ZERO)
    calmar = None if maximum_drawdown == 0 else cagr / maximum_drawdown
    invested = tuple(item.invested_capital for item in capital_curve)
    idle = tuple(item.idle_cash for item in capital_curve)
    utilisation = tuple(item.capital_utilisation_percent for item in capital_curve)
    attribution = Counter(item.exit_reason for item in trades)
    return PortfolioStatistics(
        starting_capital=_q(starting_capital),
        ending_capital=_q(ending),
        logical_trades=len(trades),
        winning_trades=len(winners),
        losing_trades=len(losers),
        breakeven_trades=len(breakeven),
        win_rate_percent=(
            None
            if not trades
            else _q(Decimal(len(winners)) / Decimal(len(trades)) * 100)
        ),
        average_winner_percent=_mean(
            tuple(item.net_return_percent for item in winners)
        ),
        average_loser_percent=_mean(tuple(item.net_return_percent for item in losers)),
        median_winner_percent=_median(
            tuple(item.net_return_percent for item in winners)
        ),
        median_loser_percent=_median(tuple(item.net_return_percent for item in losers)),
        profit_factor=(
            None if gross_loss == 0 else (gross_profit / gross_loss).quantize(_FOUR)
        ),
        expectancy_percent=_mean(returns),
        median_holding_period_days=_median(
            tuple(Decimal(item.holding_days) for item in trades)
        ),
        average_holding_period_days=_mean(
            tuple(Decimal(item.holding_days) for item in trades)
        ),
        cagr_percent=_q(cagr),
        maximum_drawdown_percent=_q(maximum_drawdown),
        ulcer_index=_q(ulcer),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=None if calmar is None else calmar.quantize(_FOUR),
        annualized_volatility_percent=_q(volatility),
        average_invested_capital=_mean(invested) or _ZERO,
        median_invested_capital=_median(invested) or _ZERO,
        maximum_invested_capital=max(invested, default=_ZERO),
        average_idle_cash=_mean(idle) or starting_capital,
        average_capital_utilisation_percent=_mean(utilisation) or _ZERO,
        days_fully_invested=sum(value >= Decimal("99.99") for value in utilisation),
        days_fully_in_cash=sum(value == 0 for value in utilisation),
        turnover_percent=(
            _ZERO
            if starting_capital <= 0
            else _q(turnover / starting_capital * Decimal("100"))
        ),
        exit_attribution=attribution,
    )


def period_returns(
    capital_curve: tuple[CapitalCurveRecord, ...], *, period: str
) -> tuple[PeriodReturn, ...]:
    groups: dict[str, list[CapitalCurveRecord]] = defaultdict(list)
    for item in capital_curve:
        key = (
            item.observed_on.strftime("%Y-%m")
            if period == "month"
            else str(item.observed_on.year)
        )
        groups[key].append(item)
    return tuple(
        PeriodReturn(
            period=key,
            opening_value=rows[0].portfolio_value,
            closing_value=rows[-1].portfolio_value,
            return_percent=(
                _ZERO
                if rows[0].portfolio_value <= 0
                else _q((rows[-1].portfolio_value / rows[0].portfolio_value - 1) * 100)
            ),
        )
        for key, rows in sorted(groups.items())
    )


def idle_capital_records(
    capital_curve: tuple[CapitalCurveRecord, ...],
) -> tuple[IdleCapitalRecord, ...]:
    groups: dict[str, list[CapitalCurveRecord]] = defaultdict(list)
    for item in capital_curve:
        groups[item.observed_on.strftime("%Y-%m")].append(item)
    return tuple(
        IdleCapitalRecord(
            period=key,
            sessions=len(rows),
            average_invested_capital=_mean(
                tuple(item.invested_capital for item in rows)
            )
            or _ZERO,
            median_invested_capital=_median(
                tuple(item.invested_capital for item in rows)
            )
            or _ZERO,
            maximum_invested_capital=max(
                (item.invested_capital for item in rows), default=_ZERO
            ),
            average_idle_cash=_mean(tuple(item.idle_cash for item in rows)) or _ZERO,
            average_utilisation_percent=_mean(
                tuple(item.capital_utilisation_percent for item in rows)
            )
            or _ZERO,
            fully_invested_days=sum(
                item.capital_utilisation_percent >= Decimal("99.99") for item in rows
            ),
            fully_in_cash_days=sum(
                item.capital_utilisation_percent == 0 for item in rows
            ),
        )
        for key, rows in sorted(groups.items())
    )


def _years(capital_curve: tuple[CapitalCurveRecord, ...]) -> Decimal:
    if len(capital_curve) < 2:
        return _ZERO
    days = (capital_curve[-1].observed_on - capital_curve[0].observed_on).days
    return Decimal(days) / Decimal("365.25")


def _annualized_ratio(
    returns: tuple[Decimal, ...],
    risk_returns: tuple[Decimal, ...],
) -> Decimal | None:
    if not returns or not risk_returns:
        return None
    risk = _std(risk_returns)
    if risk == 0:
        return None
    mean = _mean(returns) or _ZERO
    return (mean / risk * _sqrt(_TRADING_DAYS)).quantize(_FOUR)


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(_FOUR)


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(_FOUR)


def _std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return _ZERO
    mean = sum(values, _ZERO) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    return _sqrt(variance)


def _sqrt(value: Decimal) -> Decimal:
    if value <= 0:
        return _ZERO
    return value.sqrt()


def _decimal_power(base: Decimal, exponent: Decimal) -> Decimal:
    if base <= 0:
        return _ZERO
    return Decimal(str(math.pow(float(base), float(exponent))))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["idle_capital_records", "period_returns", "portfolio_statistics"]
