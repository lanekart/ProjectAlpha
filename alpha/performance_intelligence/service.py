from __future__ import annotations

import os
from pathlib import Path

from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.models import (
    PerformanceUpdateSummary,
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

    def report_lines(self) -> tuple[str, ...]:
        report = self.report_builder.build(
            entries=self.repository.load_entries(),
            outcomes=self.repository.load_outcomes(),
        )
        return render_performance_report(report)


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


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "PerformanceIntelligenceService",
    "render_update_summary",
    "resolve_ledger_path",
]
