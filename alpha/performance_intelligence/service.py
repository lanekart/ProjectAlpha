from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.models import (
    HistoricalEdge,
    PerformanceUpdateSummary,
    RecommendationLedgerEntry,
    RecommendationOutcomeStatus,
)
from alpha.performance_intelligence.outcomes import RecommendationOutcomeEvaluator
from alpha.performance_intelligence.reporting import (
    PerformanceReportBuilder,
    render_performance_report,
)
from alpha.recommendation_intelligence.models import OHLCVBar

DEFAULT_LEDGER_PATH = Path(".alpha/recommendation_ledger.json")


class PerformanceIntelligenceService:
    def __init__(
        self,
        *,
        repository: RecommendationLedgerRepository,
        future_bars_by_symbol: dict[str, tuple[OHLCVBar, ...]] | None = None,
        evaluator: RecommendationOutcomeEvaluator | None = None,
        report_builder: PerformanceReportBuilder | None = None,
    ) -> None:
        self.repository = repository
        self.future_bars_by_symbol = future_bars_by_symbol or {}
        self.evaluator = evaluator or RecommendationOutcomeEvaluator()
        self.report_builder = report_builder or PerformanceReportBuilder()

    @classmethod
    def from_path(
        cls,
        ledger_path: Path | str | None = None,
    ) -> PerformanceIntelligenceService:
        return cls(
            repository=RecommendationLedgerRepository(resolve_ledger_path(ledger_path))
        )

    def update(self) -> PerformanceUpdateSummary:
        entries = self.repository.open_entries()
        existing_outcomes = {
            outcome.recommendation_id: outcome
            for outcome in self.repository.load_outcomes()
        }
        updated_outcomes = []
        newly_entered = 0
        newly_exited = 0
        still_active = 0
        expired = 0
        missing_data_count = 0

        for entry in entries:
            bars = self.future_bars_by_symbol.get(entry.symbol, ())
            if not bars:
                missing_data_count += 1
            previous = existing_outcomes.get(entry.recommendation_id)
            outcome = self.evaluator.evaluate(entry, bars)
            updated_outcomes.append(outcome)
            if outcome.entry_triggered and (
                previous is None or not previous.entry_triggered
            ):
                newly_entered += 1
            if outcome.status is RecommendationOutcomeStatus.EXITED and (
                previous is None
                or previous.status is not RecommendationOutcomeStatus.EXITED
            ):
                newly_exited += 1
            if outcome.status is RecommendationOutcomeStatus.ACTIVE:
                still_active += 1
            if outcome.status in {
                RecommendationOutcomeStatus.EXPIRED,
                RecommendationOutcomeStatus.NOT_TRIGGERED,
            }:
                expired += 1

        self.repository.upsert_outcomes(tuple(updated_outcomes))
        return PerformanceUpdateSummary(
            recommendations_checked=len(entries),
            newly_entered=newly_entered,
            newly_exited=newly_exited,
            still_active=still_active,
            expired=expired,
            missing_data_count=missing_data_count,
        )

    def report_lines(self, *, period: str = "lifetime") -> tuple[str, ...]:
        normalized_period = period.strip().lower()
        if normalized_period != "lifetime":
            return self.period_report_lines(period=normalized_period)
        report = self.report_builder.build(
            entries=self.repository.load_entries(),
            outcomes=self.repository.load_outcomes(),
        )
        return render_performance_report(report)

    def period_report_lines(self, *, period: str) -> tuple[str, ...]:
        entries = self.repository.load_entries()
        outcomes = self.repository.load_outcomes()
        outcome_by_id = {outcome.recommendation_id: outcome for outcome in outcomes}
        groups: dict[str, list[RecommendationLedgerEntry]] = {}
        for entry in entries:
            key = _period_key(entry.generated_at.date(), period)
            groups.setdefault(key, []).append(entry)
        lines = [f"Performance Period Summary: {period}"]
        if not groups:
            return tuple(lines + ["- unavailable"])
        for key in sorted(groups):
            grouped_entries = tuple(groups[key])
            grouped_outcomes = tuple(
                outcome_by_id[entry.recommendation_id]
                for entry in grouped_entries
                if entry.recommendation_id in outcome_by_id
            )
            metrics = self.report_builder.build(
                entries=grouped_entries,
                outcomes=grouped_outcomes,
            ).metrics
            lines.append(
                f"- {key}: total={metrics.total_recommendations}, "
                f"closed={metrics.completed_trades}, "
                f"win_rate={_metric(metrics.win_rate)}, "
                f"pnl={_money(metrics.cumulative_pnl_rs)}"
            )
        return tuple(lines)

    def open_lines(self) -> tuple[str, ...]:
        entries = self.repository.open_entries()
        lines = ["Open Recommendations", f"Count: {len(entries)}"]
        if not entries:
            return tuple(lines + ["- none"])
        for entry in entries:
            lines.append(
                f"- {entry.symbol}: verdict={entry.final_verdict}, "
                f"entry={_metric(entry.confirmation_entry or entry.entry_zone_high)}, "
                f"stop={_metric(entry.stop_loss)}, target_1={_metric(entry.target_1)}"
            )
        return tuple(lines)

    def symbol_lines(self, *, symbol: str) -> tuple[str, ...]:
        normalized = symbol.strip().upper()
        entries = tuple(
            entry
            for entry in self.repository.load_entries()
            if entry.symbol == normalized
        )
        entry_ids = {entry.recommendation_id for entry in entries}
        outcomes = tuple(
            outcome
            for outcome in self.repository.load_outcomes()
            if outcome.recommendation_id in entry_ids
        )
        report = self.report_builder.build(entries=entries, outcomes=outcomes)
        lines = [
            f"Symbol Recommendation History: {normalized}",
            f"Total Recommendations: {report.metrics.total_recommendations}",
            f"Completed Trades: {report.metrics.completed_trades}",
            f"Win Rate: {_metric(report.metrics.win_rate)}",
            f"Expected Value Rs: {_money(report.metrics.expectancy_rs)}",
            f"Cumulative P&L Rs: {_money(report.metrics.cumulative_pnl_rs)}",
        ]
        if not entries:
            lines.append("- no recommendations recorded")
        return tuple(lines)

    def historical_edge(
        self,
        *,
        dimension: str,
        key: str,
        minimum_sample_size: int = 3,
    ) -> HistoricalEdge:
        classifier = _edge_classifier(dimension)
        normalized_key = key.strip().upper()
        entries = tuple(
            entry
            for entry in self.repository.load_entries()
            if classifier(entry).upper() == normalized_key
        )
        entry_ids = {entry.recommendation_id for entry in entries}
        outcomes = tuple(
            outcome
            for outcome in self.repository.load_outcomes()
            if outcome.recommendation_id in entry_ids
        )
        metrics = self.report_builder.build(entries=entries, outcomes=outcomes).metrics
        if metrics.completed_trades < minimum_sample_size:
            return HistoricalEdge(
                dimension=dimension,
                key=normalized_key,
                sample_count=metrics.completed_trades,
                win_rate=None,
                expected_value_rs=None,
                average_holding_period=None,
            )
        return HistoricalEdge(
            dimension=dimension,
            key=normalized_key,
            sample_count=metrics.completed_trades,
            win_rate=metrics.win_rate,
            expected_value_rs=metrics.expectancy_rs,
            average_holding_period=metrics.average_holding_period,
        )


def resolve_ledger_path(ledger_path: Path | str | None = None) -> Path:
    if ledger_path is not None:
        return Path(ledger_path)
    configured = os.environ.get("ALPHA_RECOMMENDATION_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_LEDGER_PATH


def render_update_summary(summary: PerformanceUpdateSummary) -> tuple[str, ...]:
    return (
        "Performance Update Summary",
        f"Recommendations Checked: {summary.recommendations_checked}",
        f"Newly Entered: {summary.newly_entered}",
        f"Newly Exited: {summary.newly_exited}",
        f"Still Active: {summary.still_active}",
        f"Expired / Not Triggered: {summary.expired}",
        f"Missing Data Count: {summary.missing_data_count}",
    )


def render_tracking_summary(
    *,
    stored_recommendations: int,
    repository: RecommendationLedgerRepository,
) -> tuple[str, ...]:
    entries = repository.load_entries()
    outcomes = repository.load_outcomes()
    report = PerformanceReportBuilder().build(entries=entries, outcomes=outcomes)
    metrics = report.metrics
    open_count = len(repository.open_entries())
    closed_count = metrics.completed_trades
    data_gaps = sum(
        1
        for outcome in outcomes
        if outcome.status is RecommendationOutcomeStatus.DATA_MISSING
    )
    lines = [
        "Recommendation Tracking:",
        f"- Stored recommendations: {len(entries)}",
        f"- New recommendations today: {stored_recommendations}",
        f"- Open recommendations: {open_count}",
        f"- Closed recommendations: {closed_count}",
        f"- Lifetime win rate: {_metric(metrics.win_rate)}",
        f"- Lifetime expected value: {_money(metrics.expectancy_rs)} per trade",
        f"- Lifetime realized P&L: {_money(metrics.total_realized_pnl_rs)}",
        f"- Data gaps: {data_gaps}",
    ]
    if not metrics.sufficient_sample:
        lines.append(
            "Performance ledger: tracking started, insufficient completed outcomes "
            "for statistical edge."
        )
    return tuple(lines)


def _period_key(value: date, period: str) -> str:
    if period == "daily":
        return value.isoformat()
    if period == "weekly":
        year, week, _ = value.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "monthly":
        return f"{value.year}-{value.month:02d}"
    if period == "yearly":
        return str(value.year)
    return "lifetime"


def _edge_classifier(
    dimension: str,
) -> Callable[[RecommendationLedgerEntry], str]:
    normalized = dimension.strip().lower()
    if normalized == "symbol":
        return lambda entry: entry.symbol
    if normalized == "setup_type":
        return lambda entry: entry.setup_type or "UNKNOWN"
    if normalized == "sector":
        return lambda entry: entry.sector or "UNKNOWN"
    if normalized == "market_regime":
        return lambda entry: entry.market_regime or "UNKNOWN"
    raise ValueError(f"Unsupported historical edge dimension: {dimension}")


def _metric(value: object) -> str:
    return "unavailable" if value is None else str(value)


def _money(value: object) -> str:
    return "unavailable" if value is None else f"₹{value}"


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "PerformanceIntelligenceService",
    "render_tracking_summary",
    "render_update_summary",
    "resolve_ledger_path",
]
