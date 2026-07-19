from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from math import sqrt
from statistics import mean, stdev

from alpha.strategy_discovery.models import (
    ConditionOperator,
    DiscoveryRow,
    DiscoveryRunConfig,
    EvaluationStage,
    FoldEvaluation,
    StrategyEvaluation,
    StrategyFamily,
    StrategyMetrics,
    StrategySpecification,
)
from alpha.strategy_discovery.walk_forward_engine import ChronologicalPartition

_TWO = Decimal("0.01")


class StrategyEvaluator:
    """Evaluate frozen strategy rules on outcome rows after signal selection."""

    def matches(self, strategy: StrategySpecification, row: DiscoveryRow) -> bool:
        if strategy.family is StrategyFamily.NO_TRADE:
            return False
        if strategy.family is StrategyFamily.RAW_RECORDED_APPROVAL:
            return row.features.get("raw_approved") == "true"
        if strategy.family is StrategyFamily.APPROVAL_POLICY_V1:
            return bool(row.approval_gate_states) and all(
                row.approval_gate_states.values()
            )
        return all(
            _condition_matches(condition, row) for condition in strategy.conditions
        )

    def selected_rows(
        self,
        strategy: StrategySpecification,
        rows: tuple[DiscoveryRow, ...],
    ) -> tuple[DiscoveryRow, ...]:
        return tuple(row for row in rows if self.matches(strategy, row))

    def net_returns(
        self,
        strategy: StrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        config: DiscoveryRunConfig,
    ) -> tuple[Decimal, ...]:
        cost = config.costs.round_trip_cost_pct
        return tuple(
            row.realised_return_pct - cost
            for row in self.selected_rows(strategy, rows)
            if row.realised_return_pct is not None
        )

    def metrics(
        self,
        *,
        strategy: StrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        config: DiscoveryRunConfig,
    ) -> StrategyMetrics:
        selected = self.selected_rows(strategy, rows)
        completed = tuple(
            row for row in selected if row.realised_return_pct is not None
        )
        cost = config.costs.round_trip_cost_pct
        gross_returns = tuple(
            row.realised_return_pct
            for row in completed
            if row.realised_return_pct is not None
        )
        net_returns = tuple(value - cost for value in gross_returns)
        winners = tuple(value for value in net_returns if value > Decimal("0"))
        losers = tuple(value for value in net_returns if value <= Decimal("0"))
        all_completed = tuple(
            row.realised_return_pct - cost
            for row in rows
            if row.realised_return_pct is not None
        )
        all_profitable = sum(1 for value in all_completed if value > Decimal("0"))
        r_values = tuple(
            _net_r(row, cost) for row in completed if _net_r(row, cost) is not None
        )
        holding_days = tuple(_holding_days(row.outcome_horizon) for row in completed)
        precision = _rate(len(winners), len(net_returns))
        ci_low, ci_high = _wilson(len(winners), len(net_returns))
        average_winner = _average(winners)
        average_loser = _average(losers)
        return StrategyMetrics(
            population_count=len(rows),
            completed_trades=len(completed),
            approval_rate_pct=_rate(len(selected), len(rows)),
            precision_pct=precision,
            precision_ci_low_pct=ci_low,
            precision_ci_high_pct=ci_high,
            recall_pct=_rate(len(winners), all_profitable),
            average_winner_pct=average_winner,
            average_loser_pct=average_loser,
            payoff_ratio=_payoff(average_winner, average_loser),
            expectancy_pct=_average(net_returns),
            profit_factor=_profit_factor(winners, losers),
            average_r_multiple=_average(
                tuple(value for value in r_values if value is not None)
            ),
            maximum_drawdown_pct=_maximum_drawdown(net_returns),
            downside_deviation_pct=_downside_deviation(net_returns),
            sharpe_ratio=_sharpe(net_returns, holding_days),
            sortino_ratio=_sortino(net_returns, holding_days),
            consecutive_losses=_consecutive_losses(net_returns),
            capital_utilisation_pct=_rate(len(selected), len(rows)),
            turnover=len(completed),
            average_holding_period_days=_average(
                tuple(Decimal(value) for value in holding_days)
            ),
            largest_winner_contribution_pct=_winner_concentration(winners),
            gross_expectancy_pct=_average(gross_returns),
            round_trip_cost_pct=cost,
        )

    def walk_forward_evaluation(
        self,
        *,
        strategy: StrategySpecification,
        partition: ChronologicalPartition,
        rows_by_id: dict[str, DiscoveryRow],
        config: DiscoveryRunConfig,
        holdout_access_id: str | None = None,
    ) -> StrategyEvaluation:
        training = self.metrics(
            strategy=strategy,
            rows=partition.training_rows,
            config=config,
        )
        validation = self.metrics(
            strategy=strategy,
            rows=partition.validation_rows,
            config=config,
        )
        fold_evaluations: list[FoldEvaluation] = []
        for fold in partition.folds:
            training_rows = tuple(
                rows_by_id[candidate_id]
                for candidate_id in fold.training_candidate_ids
                if candidate_id in rows_by_id
            )
            validation_rows = tuple(
                rows_by_id[candidate_id]
                for candidate_id in fold.validation_candidate_ids
                if candidate_id in rows_by_id
            )
            fold_evaluations.extend(
                (
                    FoldEvaluation(
                        fold_id=fold.fold_id,
                        strategy_version=strategy.strategy_version,
                        stage=EvaluationStage.TRAINING,
                        metrics=self.metrics(
                            strategy=strategy,
                            rows=training_rows,
                            config=config,
                        ),
                    ),
                    FoldEvaluation(
                        fold_id=fold.fold_id,
                        strategy_version=strategy.strategy_version,
                        stage=EvaluationStage.VALIDATION,
                        metrics=self.metrics(
                            strategy=strategy,
                            rows=validation_rows,
                            config=config,
                        ),
                    ),
                )
            )
        holdout = (
            self.metrics(
                strategy=strategy,
                rows=partition.holdout_rows,
                config=config,
            )
            if holdout_access_id is not None
            else None
        )
        return StrategyEvaluation(
            strategy=strategy,
            training_metrics=training,
            validation_metrics=validation,
            holdout_metrics=holdout,
            fold_evaluations=tuple(fold_evaluations),
            selected_for_holdout=holdout_access_id is not None,
            holdout_access_id=holdout_access_id,
        )


def _condition_matches(condition: object, row: DiscoveryRow) -> bool:
    from alpha.strategy_discovery.models import StrategyCondition

    if not isinstance(condition, StrategyCondition):
        return False
    observed = row.features.get(condition.feature_name)
    if observed is None or observed in {"unavailable", "UNAVAILABLE", "None"}:
        return False
    if condition.operator is ConditionOperator.EQUAL:
        return observed == condition.value
    if condition.operator is ConditionOperator.IS_TRUE:
        return observed.lower() == "true"
    if condition.operator is ConditionOperator.IS_FALSE:
        return observed.lower() == "false"
    try:
        observed_number = Decimal(observed)
        expected = Decimal(condition.value)
    except Exception:
        return False
    if condition.operator is ConditionOperator.GREATER_THAN_OR_EQUAL:
        return observed_number >= expected
    if condition.operator is ConditionOperator.LESS_THAN_OR_EQUAL:
        return observed_number <= expected
    return False


def _net_r(row: DiscoveryRow, cost: Decimal) -> Decimal | None:
    if row.realised_r_multiple is None or row.realised_return_pct is None:
        return None
    stop_distance = (
        abs(row.realised_return_pct / row.realised_r_multiple)
        if row.realised_r_multiple
        else None
    )
    if stop_distance is None or stop_distance <= Decimal("0"):
        return None
    return ((row.realised_return_pct - cost) / stop_distance).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values, start=Decimal("0")) / Decimal(len(values)))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _wilson(wins: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    if total <= 0:
        return None, None
    z = 1.96
    p = wins / total
    denominator = 1 + (z * z / total)
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt((p * (1 - p) / total) + z * z / (4 * total * total)) / denominator
    return (
        _quantize(Decimal(str(max(0.0, center - margin) * 100))),
        _quantize(Decimal(str(min(1.0, center + margin) * 100))),
    )


def _payoff(winner: Decimal | None, loser: Decimal | None) -> Decimal | None:
    if winner is None or loser is None or loser == Decimal("0"):
        return None
    return _quantize(winner / abs(loser))


def _profit_factor(
    winners: tuple[Decimal, ...],
    losers: tuple[Decimal, ...],
) -> Decimal | None:
    loss = abs(sum(losers, start=Decimal("0")))
    if loss == Decimal("0"):
        return None
    return _quantize(sum(winners, start=Decimal("0")) / loss)


def _maximum_drawdown(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    equity = Decimal("1")
    peak = equity
    drawdown = Decimal("0")
    for value in returns:
        equity *= Decimal("1") + value / Decimal("100")
        peak = max(peak, equity)
        if peak > Decimal("0"):
            drawdown = max(drawdown, (peak - equity) / peak * Decimal("100"))
    return _quantize(drawdown)


def _downside_deviation(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    downside = tuple(float(min(Decimal("0"), value)) for value in returns)
    return _quantize(
        Decimal(str(sqrt(sum(value * value for value in downside) / len(downside))))
    )


def _sharpe(
    returns: tuple[Decimal, ...], holding_days: tuple[int, ...]
) -> Decimal | None:
    if len(returns) < 2:
        return None
    values = tuple(float(value) for value in returns)
    deviation = stdev(values)
    if deviation == 0:
        return None
    average_hold = mean(holding_days) if holding_days else 1
    annualizer = sqrt(252 / max(1, average_hold))
    return _quantize(Decimal(str(mean(values) / deviation * annualizer)))


def _sortino(
    returns: tuple[Decimal, ...], holding_days: tuple[int, ...]
) -> Decimal | None:
    downside = _downside_deviation(returns)
    if downside is None or downside == Decimal("0"):
        return None
    average_hold = mean(holding_days) if holding_days else 1
    annualizer = Decimal(str(sqrt(252 / max(1, average_hold))))
    expectancy = _average(returns)
    return None if expectancy is None else _quantize(expectancy / downside * annualizer)


def _consecutive_losses(returns: tuple[Decimal, ...]) -> int:
    current = 0
    maximum = 0
    for value in returns:
        if value <= Decimal("0"):
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _winner_concentration(winners: tuple[Decimal, ...]) -> Decimal | None:
    total = sum(winners, start=Decimal("0"))
    if total <= Decimal("0"):
        return None
    return _quantize(max(winners) / total * Decimal("100"))


def _holding_days(horizon: str) -> int:
    digits = "".join(character for character in horizon if character.isdigit())
    return int(digits) if digits else 1


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["StrategyEvaluator"]
