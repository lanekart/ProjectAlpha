from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.application.runtime_models import RuntimeResult
from alpha.candidate_learning.aggregator import LearningSummaryAggregator
from alpha.candidate_learning.combinations import (
    IndicatorCombinationEdgeEngine,
    IndicatorCombinationEdgeReport,
    RawIndicatorCombinationEdgeEngine,
    render_indicator_combination_edge_report,
)
from alpha.candidate_learning.evaluator import CandidateForwardOutcomeEvaluator
from alpha.candidate_learning.models import CandidateDecisionRecord, LearningSummary
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcomeEvaluator,
    RawCandidateRecord,
    RawUniverseLearningAggregator,
    RawUniverseLearningSummary,
    raw_record_from_candidate,
)
from alpha.candidate_learning.recorder import (
    CandidateDecisionRecorder,
    CandidateMarketStateContext,
)
from alpha.candidate_learning.regime_shadow_live import (
    LiveRegimeShadowEvidenceEngine,
)
from alpha.candidate_learning.rendering import (
    render_learning_summary,
    render_nightly_learning_report,
)
from alpha.candidate_learning.repository import (
    LearningLedgerRepository,
    resolve_learning_ledger_path,
)
from alpha.performance_intelligence import PerformanceIntelligenceService
from alpha.performance_intelligence.recorder import source_run_id
from alpha.recommendation_intelligence.models import OHLCVBar
from alpha.strategy_regime import (
    StrategyRegimeBacktestEngine,
    StrategyRegimeBacktestRepository,
)


class NightlyLearningLoop:
    def __init__(
        self,
        *,
        repository: LearningLedgerRepository,
        future_bars_by_symbol: dict[str, tuple[OHLCVBar, ...]] | None = None,
        evaluator: CandidateForwardOutcomeEvaluator | None = None,
        aggregator: LearningSummaryAggregator | None = None,
        raw_evaluator: RawCandidateForwardOutcomeEvaluator | None = None,
        raw_aggregator: RawUniverseLearningAggregator | None = None,
    ) -> None:
        self.repository = repository
        self.future_bars_by_symbol = future_bars_by_symbol or {}
        self.evaluator = evaluator or CandidateForwardOutcomeEvaluator()
        self.aggregator = aggregator or LearningSummaryAggregator()
        self.raw_evaluator = raw_evaluator or RawCandidateForwardOutcomeEvaluator()
        self.raw_aggregator = raw_aggregator or RawUniverseLearningAggregator()

    @classmethod
    def from_path(cls, path: Path | str | None = None) -> NightlyLearningLoop:
        return cls(
            repository=LearningLedgerRepository(resolve_learning_ledger_path(path))
        )

    def record_runtime(
        self,
        runtime_result: RuntimeResult,
        *,
        market_state_context: CandidateMarketStateContext | None = None,
    ) -> tuple[int, int]:
        evaluated, stored = CandidateDecisionRecorder(self.repository).record_runtime(
            runtime_result,
            market_state_context=market_state_context,
        )
        run = runtime_result.intelligence_run
        emitted = {
            recommendation.symbol: recommendation.final_signal
            for recommendation in run.recommendations
        }
        run_id = source_run_id(runtime_result)
        raw_records = tuple(
            raw_record_from_candidate(
                candidate=candidate,
                run_id=run_id,
                created_at=runtime_result.metadata.completed_at,
                emitted_verdict_by_symbol=emitted,
                raw_rank=index,
            )
            for index, candidate in enumerate(run.raw_candidates, start=1)
        )
        self.repository.save_raw_records(raw_records)
        return evaluated, stored

    def update_outcomes(self) -> int:
        outcomes = tuple(
            self.evaluator.evaluate(
                record=record,
                bars=self.future_bars_by_symbol.get(record.symbol, ()),
            )
            for record in self.repository.load_records()
        )
        self.repository.upsert_outcomes(outcomes)
        return len(outcomes)

    def update_raw_outcomes(self) -> int:
        outcomes = tuple(
            self.raw_evaluator.evaluate(
                record=record,
                bars=self.future_bars_by_symbol.get(record.symbol, ()),
            )
            for record in self.repository.load_raw_records()
        )
        self.repository.upsert_raw_outcomes(outcomes)
        return len(outcomes)

    def summarize(self, *, period: str = "lifetime") -> LearningSummary:
        records = _filter_records(self.repository.load_records(), period=period)
        record_ids = {record.candidate_id for record in records}
        outcomes = tuple(
            outcome
            for outcome in self.repository.load_outcomes()
            if outcome.candidate_id in record_ids
        )
        summary = self.aggregator.summarize(
            records=records,
            outcomes=outcomes,
            period=period,
        )
        self.repository.save_summaries((summary,))
        return summary

    def nightly(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        refresh_backtests: bool = False,
        min_sample_size: int = 30,
    ) -> tuple[str, ...]:
        PerformanceIntelligenceService.from_path().update()
        outcomes_updated = self.update_outcomes()
        shadow_refresh = LiveRegimeShadowEvidenceEngine(
            learning_ledger_path=self.repository.path,
        ).refresh_outcomes(persist=True)
        raw_outcomes_updated = self.update_raw_outcomes()
        strategy_status = self._strategy_regime_status(
            from_date=from_date,
            to_date=to_date,
            refresh_backtests=refresh_backtests,
            min_sample_size=min_sample_size,
        )
        summary = self.summarize(period="lifetime")
        lines = render_nightly_learning_report(
            records_checked=len(self.repository.load_records()),
            outcomes_updated=outcomes_updated,
            summary=summary,
            strategy_regime_status=strategy_status,
        )
        return (
            *lines,
            f"Raw Forward Outcomes Updated: {raw_outcomes_updated}",
            "Live Regime Shadow Outcomes Checked: "
            f"{shadow_refresh.observations_checked}",
            f"Live Regime Shadow Newly Matured: {shadow_refresh.newly_matured}",
        )

    def summary_lines(self, *, period: str = "lifetime") -> tuple[str, ...]:
        return render_learning_summary(self.summarize(period=period))

    def runtime_ledger_lines(
        self,
        *,
        stored_today: int,
        evaluated_today: int,
    ) -> tuple[str, ...]:
        summary = self.summarize(period="lifetime")
        strategy_status = self._strategy_regime_status(
            from_date=None,
            to_date=None,
            refresh_backtests=False,
            min_sample_size=30,
        )
        edge = "Available" if summary.sufficient_sample else "Not yet computed"
        combination_report = self.indicator_combination_report()
        combination_edge = _combination_edge_summary(combination_report)
        return (
            "Learning Ledger:",
            f"- Candidates evaluated today: {evaluated_today}",
            f"- Candidates stored today: {stored_today}",
            f"- Total candidates tracked: {summary.total_candidates_evaluated}",
            f"- Completed forward outcomes: {summary.completed_forward_windows}",
            f"- False positives: {summary.quality.false_positive_count}",
            f"- False negatives: {summary.quality.false_negative_count}",
            f"- Correct approvals: {summary.quality.correct_approval_count}",
            f"- Correct rejects: {summary.quality.correct_reject_count}",
            f"- Learning edge: {edge}",
            f"- Indicator combination edge: {combination_edge}",
            f"- Strategy-regime backtests: {strategy_status}",
            f"- Data gaps: {summary.data_gaps}",
        )

    def indicator_combination_report(
        self,
        *,
        period: str = "lifetime",
        minimum_sample_size: int = 30,
        max_combination_size: int = 4,
        min_combination_size: int = 2,
        source: str = "historical",
    ) -> IndicatorCombinationEdgeReport:
        normalized_source = source.strip().lower()
        if normalized_source in {"historical", "raw", "replay"}:
            return self.raw_indicator_combination_report(
                period=period,
                minimum_sample_size=minimum_sample_size,
                max_combination_size=max_combination_size,
                min_combination_size=min_combination_size,
            )
        records = _filter_records(self.repository.load_records(), period=period)
        record_ids = {record.candidate_id for record in records}
        outcomes = tuple(
            outcome
            for outcome in self.repository.load_outcomes()
            if outcome.candidate_id in record_ids
        )
        return IndicatorCombinationEdgeEngine(
            minimum_sample_size=minimum_sample_size,
            max_combination_size=max_combination_size,
            min_combination_size=min_combination_size,
        ).analyze(records=records, outcomes=outcomes)

    def indicator_combination_lines(
        self,
        *,
        period: str = "lifetime",
        minimum_sample_size: int = 30,
        max_combination_size: int = 4,
        min_combination_size: int = 2,
        source: str = "historical",
    ) -> tuple[str, ...]:
        return render_indicator_combination_edge_report(
            self.indicator_combination_report(
                period=period,
                minimum_sample_size=minimum_sample_size,
                max_combination_size=max_combination_size,
                min_combination_size=min_combination_size,
                source=source,
            )
        )

    def raw_indicator_combination_report(
        self,
        *,
        period: str = "lifetime",
        minimum_sample_size: int = 30,
        max_combination_size: int = 4,
        min_combination_size: int = 2,
    ) -> IndicatorCombinationEdgeReport:
        return RawIndicatorCombinationEdgeEngine(
            minimum_sample_size=minimum_sample_size,
            max_combination_size=max_combination_size,
            min_combination_size=min_combination_size,
        ).analyze(
            records=_filter_raw_records(
                self.repository.load_raw_records(),
                period=period,
            ),
            outcomes=self.repository.load_raw_outcomes(),
        )

    def raw_runtime_lines(self) -> tuple[str, ...]:
        summary = self.raw_summary()
        filter_value = (
            "Not yet computed"
            if summary.filter_value_added is None or not summary.sufficient_sample
            else f"{summary.filter_value_added}%"
        )
        return (
            "Raw Universe Learning:",
            f"- Raw candidates scanned: {summary.total_raw_candidates}",
            f"- Raw candidates stored: {summary.total_raw_candidates}",
            f"- Emitted decisions: {summary.emitted_decisions}",
            f"- Non-emitted candidates: {summary.non_emitted_candidates}",
            f"- Top exclusion stage: {summary.top_exclusion_stage}",
            "- Forward outcomes completed: "
            f"{summary.total_raw_candidates - summary.data_gaps}",
            f"- Raw false negatives: {summary.false_negatives}",
            f"- Filter value added: {filter_value}",
            f"- Data gaps: {summary.data_gaps}",
        )

    def raw_summary(
        self,
        *,
        period: str = "lifetime",
        stage: str = "ALL",
    ) -> RawUniverseLearningSummary:
        records = self.repository.load_raw_records()
        normalized_stage = stage.strip().upper()
        if normalized_stage != "ALL":
            records = tuple(
                record
                for record in records
                if record.excluded_stage.value == normalized_stage
            )
        return self.raw_aggregator.summarize(
            records=_filter_raw_records(records, period=period),
            outcomes=self.repository.load_raw_outcomes(),
        )

    def _strategy_regime_status(
        self,
        *,
        from_date: date | None,
        to_date: date | None,
        refresh_backtests: bool,
        min_sample_size: int,
    ) -> str:
        repository = StrategyRegimeBacktestRepository()
        latest = repository.latest_run()
        if latest is None and (from_date is not None and to_date is not None):
            run = StrategyRegimeBacktestEngine().run(
                observations=(),
                from_date=from_date,
                to_date=to_date,
                minimum_sample_size=min_sample_size,
            )
            repository.save_run(run)
            return "fresh" if run.results else "missing"
        if refresh_backtests and from_date is not None and to_date is not None:
            run = StrategyRegimeBacktestEngine().run(
                observations=(),
                from_date=from_date,
                to_date=to_date,
                minimum_sample_size=min_sample_size,
            )
            repository.save_run(run)
            return "fresh" if run.results else "missing"
        return "missing" if latest is None else "fresh"


def _filter_records(
    records: tuple[CandidateDecisionRecord, ...],
    *,
    period: str,
) -> tuple[CandidateDecisionRecord, ...]:
    normalized = period.strip().lower()
    if normalized == "lifetime":
        return records
    # The persisted summary key is explicit; detailed date slicing can be widened
    # when the market data scheduler passes concrete calendar windows.
    return records


def _filter_raw_records(
    records: tuple[RawCandidateRecord, ...],
    *,
    period: str,
) -> tuple[RawCandidateRecord, ...]:
    normalized = period.strip().lower()
    if normalized == "lifetime":
        return records
    return records


def _combination_edge_summary(report: IndicatorCombinationEdgeReport) -> str:
    if not report.strongest:
        return (
            "insufficient evidence "
            f"({report.completed_windows}/{report.minimum_sample_size} completed)"
        )
    best = report.strongest[0]
    return (
        f"{best.label} in {best.market_regime}, "
        f"samples={best.completed_count}, expectancy={best.expectancy_pct}%"
    )


__all__ = ["NightlyLearningLoop"]
