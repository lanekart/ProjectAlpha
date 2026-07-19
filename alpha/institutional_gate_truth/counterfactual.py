from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from alpha.institutional_gate_truth.models import (
    CounterfactualCurvePoint,
    CounterfactualStatistics,
    CounterfactualTrade,
    RejectionAssessment,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_TRADING_DAYS = Decimal("252")


class CounterfactualPortfolioEngine:
    """Equal-weight all entered rejected signals without ranking or optimization."""

    def run(
        self,
        *,
        assessments: tuple[RejectionAssessment, ...],
        future_bars: pd.DataFrame,
        sessions: tuple[date, ...],
        starting_capital: Decimal,
        round_trip_friction_percent: Decimal,
    ) -> tuple[
        tuple[CounterfactualTrade, ...],
        tuple[CounterfactualCurvePoint, ...],
        CounterfactualStatistics,
    ]:
        trades = _trades(assessments)
        daily_trade_returns = _daily_trade_returns(
            trades=trades,
            frame=future_bars,
            friction_percent=round_trip_friction_percent,
        )
        curve = _curve(
            sessions=sessions,
            returns=daily_trade_returns,
            starting_capital=starting_capital,
        )
        completed_ids = {
            item.candidate.candidate_id
            for item in assessments
            if item.planned_outcome.entered
            and (
                item.planned_outcome.complete
                or item.planned_outcome.exit_reason in {"STOP", "TARGET"}
            )
        }
        completed = tuple(item for item in trades if item.candidate_id in completed_ids)
        winners = tuple(item for item in completed if item.net_return_percent > 0)
        losers = tuple(item for item in completed if item.net_return_percent < 0)
        breakeven = tuple(item for item in completed if item.net_return_percent == 0)
        daily = tuple(item.daily_return_percent / Decimal("100") for item in curve[1:])
        downside = tuple(value for value in daily if value < 0)
        average_winner = _mean(tuple(item.net_return_percent for item in winners))
        average_loser = _mean(tuple(item.net_return_percent for item in losers))
        payoff = (
            None
            if average_winner is None or average_loser is None or average_loser == 0
            else (average_winner / abs(average_loser)).quantize(_FOUR)
        )
        entered = len(trades)
        statistics = CounterfactualStatistics(
            starting_capital=_q(starting_capital),
            ending_capital=(
                _q(curve[-1].portfolio_value) if curve else _q(starting_capital)
            ),
            rejected_signals=len(assessments),
            entered_trades=entered,
            not_entered=len(assessments) - entered,
            completed_trades=len(completed),
            winning_trades=len(winners),
            losing_trades=len(losers),
            breakeven_trades=len(breakeven),
            win_rate_percent=_rate(len(winners), len(completed)),
            average_winner_percent=average_winner,
            average_loser_percent=average_loser,
            payoff_ratio=payoff,
            expectancy_percent=_mean(
                tuple(item.net_return_percent for item in completed)
            ),
            cagr_percent=_cagr(curve, starting_capital),
            maximum_drawdown_percent=(
                max((abs(item.drawdown_percent) for item in curve), default=_ZERO)
                if curve
                else None
            ),
            sharpe_ratio=_annualized_ratio(daily, daily),
            sortino_ratio=_annualized_ratio(daily, downside),
            unresolved_trades=entered - len(completed),
            methodology=(
                "Every entered rejected BUY is an independent logical trade. "
                "Daily portfolio return is the equal-weight mean of all active "
                "logical trades; no ranking, selection, or gate threshold is used."
            ),
        )
        return trades, curve, statistics


def _trades(
    assessments: tuple[RejectionAssessment, ...],
) -> tuple[CounterfactualTrade, ...]:
    rows: list[CounterfactualTrade] = []
    for item in assessments:
        outcome = item.planned_outcome
        candidate = item.candidate
        if not outcome.entered:
            continue
        if any(
            value is None
            for value in (
                outcome.entry_date,
                outcome.execution_price,
                outcome.exit_date,
                outcome.exit_price,
                outcome.net_return_percent,
                outcome.realized_r,
                candidate.prospective_stop,
                candidate.prospective_target,
            )
        ):
            continue
        assert outcome.entry_date is not None
        assert outcome.execution_price is not None
        assert outcome.exit_date is not None
        assert outcome.exit_price is not None
        assert outcome.net_return_percent is not None
        assert outcome.realized_r is not None
        assert candidate.prospective_stop is not None
        assert candidate.prospective_target is not None
        rows.append(
            CounterfactualTrade(
                candidate_id=candidate.candidate_id,
                symbol=candidate.symbol,
                signal_date=candidate.observed_on,
                entry_date=outcome.entry_date,
                exit_date=outcome.exit_date,
                entry_price=outcome.execution_price,
                exit_price=outcome.exit_price,
                stop_price=candidate.prospective_stop,
                target_price=candidate.prospective_target,
                net_return_percent=outcome.net_return_percent,
                realized_r=outcome.realized_r,
                holding_sessions=max(1, outcome.holding_sessions),
                exit_reason=outcome.exit_reason,
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.entry_date, item.candidate_id)))


def _daily_trade_returns(
    *,
    trades: tuple[CounterfactualTrade, ...],
    frame: pd.DataFrame,
    friction_percent: Decimal,
) -> dict[date, list[Decimal]]:
    by_id = {item.candidate_id: item for item in trades}
    grouped: dict[str, list[Mapping[Hashable, Any]]] = defaultdict(list)
    if not frame.empty:
        for row in frame.sort_values(["candidate_id", "trade_date"]).to_dict("records"):
            candidate_id = str(row["candidate_id"])
            if candidate_id in by_id:
                grouped[candidate_id].append(row)
    result: dict[date, list[Decimal]] = defaultdict(list)
    half_cost = friction_percent / Decimal("200")
    for candidate_id, trade in by_id.items():
        previous = trade.entry_price
        first = True
        for bar_row in grouped.get(candidate_id, ()):
            observed_on = _date(bar_row["trade_date"])
            if observed_on < trade.entry_date or observed_on > trade.exit_date:
                continue
            ending = (
                trade.exit_price
                if observed_on == trade.exit_date
                else Decimal(str(bar_row["close"]))
            )
            daily_return = ending / previous - _ONE
            if first:
                daily_return -= half_cost
                first = False
            if observed_on == trade.exit_date:
                daily_return -= half_cost
            result[observed_on].append(daily_return)
            previous = ending
            if observed_on == trade.exit_date:
                break
    return result


def _curve(
    *,
    sessions: tuple[date, ...],
    returns: dict[date, list[Decimal]],
    starting_capital: Decimal,
) -> tuple[CounterfactualCurvePoint, ...]:
    value = starting_capital
    peak = starting_capital
    rows: list[CounterfactualCurvePoint] = []
    for observed_on in sessions:
        active = returns.get(observed_on, ())
        daily = _ZERO if not active else sum(active, _ZERO) / Decimal(len(active))
        value *= _ONE + daily
        peak = max(peak, value)
        drawdown = _ZERO if peak <= 0 else (value / peak - _ONE) * Decimal("100")
        rows.append(
            CounterfactualCurvePoint(
                observed_on=observed_on,
                portfolio_value=_q(value),
                daily_return_percent=_q(daily * Decimal("100")),
                drawdown_percent=_q(drawdown),
                active_trades=len(active),
            )
        )
    return tuple(rows)


def _cagr(
    curve: tuple[CounterfactualCurvePoint, ...],
    starting_capital: Decimal,
) -> Decimal | None:
    if len(curve) < 2 or starting_capital <= 0:
        return None
    days = (curve[-1].observed_on - curve[0].observed_on).days
    ending = curve[-1].portfolio_value
    if days <= 0 or ending <= 0:
        return None
    years = Decimal(days) / Decimal("365.25")
    result = Decimal(
        str(math.pow(float(ending / starting_capital), float(_ONE / years)))
    )
    return _q((result - _ONE) * Decimal("100"))


def _annualized_ratio(
    values: tuple[Decimal, ...],
    risk_values: tuple[Decimal, ...],
) -> Decimal | None:
    if len(values) < 2 or len(risk_values) < 2:
        return None
    risk = _std(risk_values)
    if risk == 0:
        return None
    mean = sum(values, _ZERO) / Decimal(len(values))
    return (mean / risk * _TRADING_DAYS.sqrt()).quantize(_FOUR)


def _std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return _ZERO
    mean = sum(values, _ZERO) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    return variance.sqrt() if variance > 0 else _ZERO


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(sum(values, _ZERO) / Decimal(len(values)))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _q(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["CounterfactualPortfolioEngine"]
