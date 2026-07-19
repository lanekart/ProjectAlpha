from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from alpha.performance_intelligence.models import (
    PerformanceMetrics,
    PerformanceReport,
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
    confidence_bucket,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR_PLACES = Decimal("0.0001")
_TWO_PLACES = Decimal("0.01")


class PerformanceReportBuilder:
    def __init__(self, *, minimum_sample_size: int = 10) -> None:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size must be positive")
        self.minimum_sample_size = minimum_sample_size

    def build(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
    ) -> PerformanceReport:
        outcome_by_id = {outcome.recommendation_id: outcome for outcome in outcomes}
        metrics = self._metrics(entries=entries, outcomes=outcomes)
        breakdowns = {
            **self._breakdown(
                "verdict",
                entries,
                outcome_by_id,
                lambda entry: entry.final_verdict,
            ),
            **self._breakdown(
                "setup",
                entries,
                outcome_by_id,
                lambda entry: entry.setup_type or "UNKNOWN",
            ),
            **self._breakdown(
                "regime",
                entries,
                outcome_by_id,
                lambda entry: entry.market_regime or "UNKNOWN",
            ),
            **self._breakdown(
                "sector",
                entries,
                outcome_by_id,
                lambda entry: entry.sector or "UNKNOWN",
            ),
            **self._breakdown(
                "confidence",
                entries,
                outcome_by_id,
                lambda entry: confidence_bucket(entry.confidence),
            ),
        }
        return PerformanceReport(
            metrics=metrics,
            breakdowns=MappingProxyType(dict(sorted(breakdowns.items()))),
        )

    def _breakdown(
        self,
        prefix: str,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcome_by_id: dict[str, RecommendationOutcome],
        classifier: Callable[[RecommendationLedgerEntry], str],
    ) -> dict[str, PerformanceMetrics]:
        groups: dict[str, list[RecommendationLedgerEntry]] = {}
        for entry in entries:
            groups.setdefault(classifier(entry), []).append(entry)

        result: dict[str, PerformanceMetrics] = {}
        for label, grouped_entries in groups.items():
            grouped_outcomes = tuple(
                outcome_by_id[entry.recommendation_id]
                for entry in grouped_entries
                if entry.recommendation_id in outcome_by_id
            )
            result[f"{prefix}:{label}"] = self._metrics(
                entries=tuple(grouped_entries),
                outcomes=grouped_outcomes,
            )
        return result

    def _metrics(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: Iterable[RecommendationOutcome],
    ) -> PerformanceMetrics:
        outcome_tuple = tuple(outcomes)
        completed = tuple(
            outcome
            for outcome in outcome_tuple
            if outcome.status
            in {
                RecommendationOutcomeStatus.EXITED,
                RecommendationOutcomeStatus.EXPIRED,
            }
            and outcome.realized_r_multiple is not None
        )
        wins = tuple(
            outcome
            for outcome in completed
            if outcome.realized_r_multiple is not None
            and outcome.realized_r_multiple > _ZERO
        )
        losses = tuple(
            outcome
            for outcome in completed
            if outcome.realized_r_multiple is not None
            and outcome.realized_r_multiple < _ZERO
        )
        breakeven = tuple(
            outcome
            for outcome in completed
            if outcome.realized_r_multiple is not None
            and outcome.realized_r_multiple == _ZERO
        )
        gains = tuple(
            outcome.realized_percent_return
            for outcome in wins
            if outcome.realized_percent_return is not None
        )
        loss_returns = tuple(
            outcome.realized_percent_return
            for outcome in losses
            if outcome.realized_percent_return is not None
        )
        gain_rs = tuple(
            outcome.realized_pnl_rs
            for outcome in wins
            if outcome.realized_pnl_rs is not None
        )
        loss_rs = tuple(
            outcome.realized_pnl_rs
            for outcome in losses
            if outcome.realized_pnl_rs is not None
        )
        realized_pnl = tuple(
            outcome.realized_pnl_rs
            for outcome in completed
            if outcome.realized_pnl_rs is not None
        )
        unrealized_pnl = tuple(
            outcome.unrealized_pnl_rs
            for outcome in outcome_tuple
            if outcome.unrealized_pnl_rs is not None
        )
        percent_returns = tuple(
            outcome.realized_percent_return
            for outcome in completed
            if outcome.realized_percent_return is not None
        )
        holding_days = tuple(
            Decimal(outcome.holding_period_days) for outcome in completed
        )
        total_gain_r = sum(
            (
                outcome.realized_r_multiple
                for outcome in wins
                if outcome.realized_r_multiple is not None
            ),
            _ZERO,
        )
        total_loss_r = sum(
            (
                abs(outcome.realized_r_multiple)
                for outcome in losses
                if outcome.realized_r_multiple is not None
            ),
            _ZERO,
        )
        total_recommendations = len(entries)
        pending_count = len(
            tuple(
                outcome
                for outcome in outcome_tuple
                if outcome.status is RecommendationOutcomeStatus.PENDING
            )
        )
        active_count = len(
            tuple(
                outcome
                for outcome in outcome_tuple
                if outcome.status is RecommendationOutcomeStatus.ACTIVE
            )
        )
        not_triggered = len(
            tuple(
                outcome
                for outcome in outcome_tuple
                if outcome.status is RecommendationOutcomeStatus.NOT_TRIGGERED
            )
        )
        sample_count = len(completed)
        sufficient = sample_count >= self.minimum_sample_size
        return PerformanceMetrics(
            total_recommendations=total_recommendations,
            completed_trades=sample_count,
            win_rate=_rate(len(wins), sample_count),
            loss_rate=_rate(len(losses), sample_count),
            average_r=_average(
                tuple(
                    outcome.realized_r_multiple
                    for outcome in completed
                    if outcome.realized_r_multiple is not None
                )
            ),
            expectancy=_average(
                tuple(
                    outcome.realized_r_multiple
                    for outcome in completed
                    if outcome.realized_r_multiple is not None
                )
            ),
            average_gain=_average(gains),
            average_loss=_average(loss_returns),
            profit_factor=None
            if total_loss_r == _ZERO
            else (total_gain_r / total_loss_r).quantize(
                _FOUR_PLACES,
                rounding=ROUND_HALF_UP,
            ),
            average_holding_period=_average(holding_days),
            target_1_hit_rate=_rate(
                len(tuple(outcome for outcome in completed if outcome.target_1_hit)),
                sample_count,
            ),
            target_2_hit_rate=_rate(
                len(tuple(outcome for outcome in completed if outcome.target_2_hit)),
                sample_count,
            ),
            target_3_hit_rate=_rate(
                len(tuple(outcome for outcome in completed if outcome.target_3_hit)),
                sample_count,
            ),
            stop_hit_rate=_rate(
                len(tuple(outcome for outcome in completed if outcome.stop_hit)),
                sample_count,
            ),
            not_triggered_rate=_rate(not_triggered, total_recommendations),
            pending_count=pending_count,
            active_count=active_count,
            sample_count=sample_count,
            sufficient_sample=sufficient,
            average_gain_rs=_average(gain_rs),
            average_loss_rs=_average(loss_rs),
            total_realized_pnl_rs=_sum_or_none(realized_pnl),
            total_unrealized_pnl_rs=_sum_or_none(unrealized_pnl),
            cumulative_pnl_rs=_sum_or_none(realized_pnl + unrealized_pnl),
            expectancy_pct=_expectancy(
                win_rate=_rate(len(wins), sample_count),
                loss_rate=_rate(len(losses), sample_count),
                average_gain=_average(gains),
                average_loss=_average(loss_returns),
            ),
            expectancy_rs=_expectancy(
                win_rate=_rate(len(wins), sample_count),
                loss_rate=_rate(len(losses), sample_count),
                average_gain=_average(gain_rs),
                average_loss=_average(loss_rs),
            ),
            best_trade_rs=max(realized_pnl) if realized_pnl else None,
            worst_trade_rs=min(realized_pnl) if realized_pnl else None,
            best_trade_pct=max(percent_returns) if percent_returns else None,
            worst_trade_pct=min(percent_returns) if percent_returns else None,
            median_holding_period=_median(holding_days),
            breakeven_trades=len(breakeven),
            winning_trades=len(wins),
            losing_trades=len(losses),
        )


def render_performance_report(report: PerformanceReport) -> tuple[str, ...]:
    metrics = report.metrics
    lines = [
        "Performance Intelligence Report",
        f"Total Recommendations: {metrics.total_recommendations}",
        f"Completed Trades: {metrics.completed_trades}",
        f"Win Rate: {_metric(metrics.win_rate)}",
        f"Loss Rate: {_metric(metrics.loss_rate)}",
        f"Average R: {_metric(metrics.average_r)}",
        f"Expectancy: {_metric(metrics.expectancy)}",
        f"Average Gain: {_metric(metrics.average_gain)}",
        f"Average Loss: {_metric(metrics.average_loss)}",
        f"Average Gain Rs: {_money(metrics.average_gain_rs)}",
        f"Average Loss Rs: {_money(metrics.average_loss_rs)}",
        f"Total Realized P&L Rs: {_money(metrics.total_realized_pnl_rs)}",
        f"Total Unrealized P&L Rs: {_money(metrics.total_unrealized_pnl_rs)}",
        f"Cumulative P&L Rs: {_money(metrics.cumulative_pnl_rs)}",
        f"Expectancy Pct: {_metric(metrics.expectancy_pct)}",
        f"Expectancy Rs: {_money(metrics.expectancy_rs)}",
        f"Profit Factor: {_metric(metrics.profit_factor)}",
        f"Average Holding Period: {_metric(metrics.average_holding_period)}",
        f"Target 1 Hit Rate: {_metric(metrics.target_1_hit_rate)}",
        f"Target 2 Hit Rate: {_metric(metrics.target_2_hit_rate)}",
        f"Target 3 Hit Rate: {_metric(metrics.target_3_hit_rate)}",
        f"Stop Hit Rate: {_metric(metrics.stop_hit_rate)}",
        f"Not-Triggered Rate: {_metric(metrics.not_triggered_rate)}",
        f"Pending Count: {metrics.pending_count}",
        f"Active Count: {metrics.active_count}",
        f"Winning Trades: {metrics.winning_trades}",
        f"Losing Trades: {metrics.losing_trades}",
        f"Breakeven Trades: {metrics.breakeven_trades}",
        f"Best Trade Rs: {_money(metrics.best_trade_rs)}",
        f"Worst Trade Rs: {_money(metrics.worst_trade_rs)}",
        f"Best Trade Pct: {_metric(metrics.best_trade_pct)}",
        f"Worst Trade Pct: {_metric(metrics.worst_trade_pct)}",
        f"Median Holding Period: {_metric(metrics.median_holding_period)}",
        "Max Drawdown: unavailable; equity curve support is not yet wired.",
    ]
    if not metrics.sufficient_sample:
        lines.append(
            "Sample Size: "
            f"{metrics.sample_count} completed trades; insufficient data for "
            "statistically reliable performance."
        )
    lines.append("")
    lines.append("Breakdowns:")
    if not report.breakdowns:
        lines.append("- unavailable")
    for label, breakdown in report.breakdowns.items():
        lines.append(
            f"- {label}: trades={breakdown.completed_trades}, "
            f"win_rate={_metric(breakdown.win_rate)}, "
            f"avg_r={_metric(breakdown.average_r)}"
        )
    return tuple(lines)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _sum_or_none(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, _ZERO).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _expectancy(
    *,
    win_rate: Decimal | None,
    loss_rate: Decimal | None,
    average_gain: Decimal | None,
    average_loss: Decimal | None,
) -> Decimal | None:
    if (
        win_rate is None
        or loss_rate is None
        or average_gain is None
        or average_loss is None
    ):
        return None
    return ((win_rate * average_gain) - (loss_rate * abs(average_loss))).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle].quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return ((ordered[middle - 1] + ordered[middle]) / Decimal("2")).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _metric(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return str(value)


def _money(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"₹{value}"


__all__ = ["PerformanceReportBuilder", "render_performance_report"]
