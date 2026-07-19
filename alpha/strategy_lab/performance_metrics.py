from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt
from statistics import mean, median, stdev

from alpha.strategy_discovery.models import (
    DiscoveryRow,
    StrategyFamily,
    StrategySpecification,
)
from alpha.strategy_discovery.strategy_evaluator import StrategyEvaluator
from alpha.strategy_lab.models import (
    ExecutionAssumptionProfile,
    LabStrategySpecification,
    StrategyPerformanceMetrics,
)

_TWO = Decimal("0.01")


class PerformanceMetricsEngine:
    """Calculate comparable gross, net, risk, and evidence metrics."""

    def __init__(self, evaluator: StrategyEvaluator | None = None) -> None:
        self.evaluator = evaluator or StrategyEvaluator()

    def selected_rows(
        self,
        strategy: LabStrategySpecification,
        rows: tuple[DiscoveryRow, ...],
    ) -> tuple[DiscoveryRow, ...]:
        return self.evaluator.selected_rows(_source_strategy(strategy), rows)

    def evaluate(
        self,
        *,
        strategy: LabStrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        profile: ExecutionAssumptionProfile,
    ) -> StrategyPerformanceMetrics:
        selected = self.selected_rows(strategy, rows)
        completed = tuple(
            item for item in selected if item.realised_return_pct is not None
        )
        gross = tuple(
            item.realised_return_pct
            for item in completed
            if item.realised_return_pct is not None
        )
        cost = profile.round_trip_cost_pct
        net = tuple(value - cost for value in gross)
        winners = tuple(value for value in net if value > Decimal("0"))
        losers = tuple(value for value in net if value < Decimal("0"))
        breakeven = tuple(value for value in net if value == Decimal("0"))
        all_completed = tuple(
            item for item in rows if item.realised_return_pct is not None
        )
        profitable_ids = {
            item.candidate_id
            for item in all_completed
            if item.realised_return_pct is not None
            and item.realised_return_pct - cost > Decimal("0")
        }
        selected_ids = {item.candidate_id for item in completed}
        false_negatives = len(profitable_ids - selected_ids)
        r_values = tuple(
            item.realised_r_multiple
            for item in completed
            if item.realised_r_multiple is not None
        )
        mfe = tuple(item.mfe_pct for item in completed if item.mfe_pct is not None)
        mae = tuple(item.mae_pct for item in completed if item.mae_pct is not None)
        holding = tuple(
            Decimal(_holding_days(item.outcome_horizon)) for item in completed
        )
        win_rate = _rate(len(winners), len(net))
        ci_low, ci_high = _wilson(len(winners), len(net))
        drawdowns = _drawdowns(net)
        maximum_drawdown = max(drawdowns, default=None)
        downside = _downside_deviation(net)
        sharpe = _sharpe(net, holding)
        sortino = _sortino(net, holding)
        starting = Decimal("100000")
        ending = _ending_capital(starting, net, profile.capital_per_trade_pct)
        total_return = _q((ending - starting) / starting * Decimal("100"))
        first_date = min(
            (item.candidate_timestamp.date() for item in completed), default=None
        )
        last_date = max(
            (item.candidate_timestamp.date() for item in completed), default=None
        )
        days = (
            0
            if first_date is None or last_date is None
            else (last_date - first_date).days
        )
        cagr = _cagr(starting, ending, days)
        period_values = _annual_expectancies(completed, cost)
        positive_periods = sum(
            1 for value in period_values.values() if value > Decimal("0")
        )
        symbol_counts = Counter(item.symbol for item in completed)
        average_winner = _average(winners)
        average_loser = _average(losers)
        capital_utilisation = _rate(len(selected), len(rows))
        return StrategyPerformanceMetrics(
            signals_generated=len(selected),
            trades_entered=len(completed),
            missed_entries=len(selected) - len(completed),
            completed_trades=len(completed),
            winning_trades=len(winners),
            losing_trades=len(losers),
            breakeven_trades=len(breakeven),
            win_rate_pct=win_rate,
            loss_rate_pct=_rate(len(losers), len(net)),
            precision_pct=win_rate,
            precision_ci_low_pct=ci_low,
            precision_ci_high_pct=ci_high,
            recall_pct=_rate(len(selected_ids & profitable_ids), len(profitable_ids)),
            false_positives=len(losers),
            false_negatives=false_negatives,
            average_return_pct=_average(net),
            median_return_pct=_median(net),
            average_winner_pct=average_winner,
            median_winner_pct=_median(winners),
            average_loser_pct=average_loser,
            median_loser_pct=_median(losers),
            payoff_ratio=_ratio(average_winner, _absolute(average_loser)),
            expectancy_pct=_average(net),
            gross_expectancy_pct=_average(gross),
            profit_factor=_profit_factor(winners, losers),
            average_r_multiple=_average(r_values),
            median_r_multiple=_median(r_values),
            average_mfe_pct=_average(mfe),
            average_mae_pct=_average(mae),
            average_holding_period_days=_average(holding),
            maximum_drawdown_pct=maximum_drawdown,
            average_drawdown_pct=_average(drawdowns),
            downside_deviation_pct=downside,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=_ratio(cagr, maximum_drawdown),
            longest_losing_streak=_streak(net, winning=False),
            longest_winning_streak=_streak(net, winning=True),
            worst_trade_pct=min(net, default=None),
            best_trade_pct=max(net, default=None),
            tail_loss_pct=_tail_loss(net),
            gap_loss_exposure_pct=None,
            starting_capital=starting,
            ending_capital=ending,
            cagr_pct=cagr,
            total_return_pct=total_return,
            capital_utilisation_pct=capital_utilisation,
            turnover=len(completed),
            maximum_concurrent_positions=None,
            cash_drag_pct=(
                None
                if capital_utilisation is None
                else _q(Decimal("100") - capital_utilisation)
            ),
            largest_winner_contribution_pct=_winner_concentration(winners),
            symbol_concentration_pct=(
                None
                if not completed
                else _q(
                    Decimal(max(symbol_counts.values()))
                    / Decimal(len(completed))
                    * Decimal("100")
                )
            ),
            positive_period_pct=_rate(positive_periods, len(period_values)),
            years_represented=len(period_values),
            symbols_represented=len(symbol_counts),
            net_cost_drag_pct=(None if not completed else _q(cost)),
        )


def _source_strategy(item: LabStrategySpecification) -> StrategySpecification:
    return StrategySpecification(
        strategy_version=item.source_strategy_version,
        strategy_hash=item.strategy_hash,
        name=item.name,
        family=StrategyFamily(item.family),
        conditions=item.conditions,
        benchmark=item.benchmark,
        description="Strategy Lab composition of an existing discovery rule.",
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    return (
        None
        if not values
        else _q(sum(values, start=Decimal("0")) / Decimal(len(values)))
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    return None if not values else _q(Decimal(str(median(values))))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _q(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == Decimal("0"):
        return None
    return _q(numerator / denominator)


def _absolute(value: Decimal | None) -> Decimal | None:
    return None if value is None else abs(value)


def _wilson(wins: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    if total <= 0:
        return None, None
    z = 1.96
    p = wins / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return _q(Decimal(str(max(0.0, center - margin) * 100))), _q(
        Decimal(str(min(1.0, center + margin) * 100))
    )


def _profit_factor(
    winners: tuple[Decimal, ...], losers: tuple[Decimal, ...]
) -> Decimal | None:
    losses = abs(sum(losers, start=Decimal("0")))
    if losses == Decimal("0"):
        return None
    return _q(sum(winners, start=Decimal("0")) / losses)


def _drawdowns(returns: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    equity = Decimal("1")
    peak = equity
    values: list[Decimal] = []
    for item in returns:
        equity *= Decimal("1") + item / Decimal("100")
        peak = max(peak, equity)
        values.append(_q((peak - equity) / peak * Decimal("100")))
    return tuple(values)


def _downside_deviation(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    negatives = tuple(float(min(Decimal("0"), item)) for item in returns)
    return _q(
        Decimal(str(sqrt(sum(item * item for item in negatives) / len(negatives))))
    )


def _sharpe(
    returns: tuple[Decimal, ...], holding: tuple[Decimal, ...]
) -> Decimal | None:
    if len(returns) < 2:
        return None
    values = tuple(float(item) for item in returns)
    deviation = stdev(values)
    if deviation == 0:
        return None
    average_hold = float(_average(holding) or Decimal("1"))
    return _q(Decimal(str(mean(values) / deviation * sqrt(252 / max(1, average_hold)))))


def _sortino(
    returns: tuple[Decimal, ...], holding: tuple[Decimal, ...]
) -> Decimal | None:
    downside = _downside_deviation(returns)
    expectancy = _average(returns)
    if downside is None or downside == Decimal("0") or expectancy is None:
        return None
    average_hold = float(_average(holding) or Decimal("1"))
    return _q(expectancy / downside * Decimal(str(sqrt(252 / max(1, average_hold)))))


def _ending_capital(
    starting: Decimal, returns: tuple[Decimal, ...], allocation_pct: Decimal
) -> Decimal:
    value = starting
    fraction = allocation_pct / Decimal("100")
    for item in returns:
        value *= Decimal("1") + item / Decimal("100") * fraction
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def _cagr(starting: Decimal, ending: Decimal, days: int) -> Decimal | None:
    if days < 365 or starting <= Decimal("0") or ending <= Decimal("0"):
        return None
    years = days / 365.25
    return _q(Decimal(str(((float(ending / starting)) ** (1 / years) - 1) * 100)))


def _streak(returns: tuple[Decimal, ...], *, winning: bool) -> int:
    current = 0
    maximum = 0
    for item in returns:
        match = item > Decimal("0") if winning else item < Decimal("0")
        if match:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _tail_loss(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    ordered = tuple(sorted(returns))
    count = max(1, len(ordered) // 10)
    return _average(ordered[:count])


def _winner_concentration(winners: tuple[Decimal, ...]) -> Decimal | None:
    total = sum(winners, start=Decimal("0"))
    if total <= Decimal("0"):
        return None
    return _q(max(winners) / total * Decimal("100"))


def _annual_expectancies(
    rows: tuple[DiscoveryRow, ...], cost: Decimal
) -> dict[int, Decimal]:
    grouped: dict[int, list[Decimal]] = {}
    for item in rows:
        if item.realised_return_pct is not None:
            grouped.setdefault(item.candidate_timestamp.year, []).append(
                item.realised_return_pct - cost
            )
    return {
        year: _average(tuple(values)) or Decimal("0")
        for year, values in grouped.items()
    }


def _holding_days(value: str) -> int:
    digits = "".join(item for item in value if item.isdigit())
    return int(digits) if digits else 1


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["PerformanceMetricsEngine"]
