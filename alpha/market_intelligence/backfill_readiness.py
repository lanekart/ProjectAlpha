from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd

from alpha.market_intelligence.benchmark import (
    BenchmarkConfiguration,
    BenchmarkFeatureCompleteness,
    BenchmarkStateBuilder,
    canonical_benchmark_configuration,
)
from alpha.market_intelligence.snapshots import MARKET_STATE_CLASSIFIER_VERSION
from alpha.provenance import (
    ComponentCompatibility,
    EvidenceReliability,
    HistoricalBackfillVersionEligibility,
    current_market_classifier_fingerprint,
)


class BenchmarkDateAlignment(StrEnum):
    SAME_TRADING_DAY = "SAME_TRADING_DAY"
    PREVIOUS_COMPLETED_SESSION = "PREVIOUS_COMPLETED_SESSION"
    VALID_CARRIED_FORWARD = "VALID_CARRIED_FORWARD"
    STALE_CARRIED_FORWARD = "STALE_CARRIED_FORWARD"
    NO_BAR_AT_OR_BEFORE_DATE = "NO_BAR_AT_OR_BEFORE_DATE"
    DATE_BEFORE_BENCHMARK_HISTORY = "DATE_BEFORE_BENCHMARK_HISTORY"
    DATE_AFTER_BENCHMARK_HISTORY = "DATE_AFTER_BENCHMARK_HISTORY"
    TIMESTAMP_MISMATCH = "TIMESTAMP_MISMATCH"
    CALENDAR_ALIGNMENT_ERROR = "CALENDAR_ALIGNMENT_ERROR"


class BenchmarkLookbackGapReason(StrEnum):
    FEWER_THAN_200_PRIOR_BARS = "FEWER_THAN_200_PRIOR_BARS"
    BENCHMARK_HISTORY_STARTS_TOO_LATE = "BENCHMARK_HISTORY_STARTS_TOO_LATE"
    BENCHMARK_QUERY_WINDOW_TRUNCATED = "BENCHMARK_QUERY_WINDOW_TRUNCATED"
    BENCHMARK_SYMBOL_MISMATCH = "BENCHMARK_SYMBOL_MISMATCH"
    BENCHMARK_SOURCE_FRAGMENTED = "BENCHMARK_SOURCE_FRAGMENTED"
    DUPLICATE_DATE_COLLAPSE = "DUPLICATE_DATE_COLLAPSE"
    MISSING_TRADING_SESSIONS = "MISSING_TRADING_SESSIONS"
    INVALID_OR_NONFINITE_CLOSES = "INVALID_OR_NONFINITE_CLOSES"
    DATE_NORMALIZATION_MISMATCH = "DATE_NORMALIZATION_MISMATCH"
    TIMEZONE_ALIGNMENT_MISMATCH = "TIMEZONE_ALIGNMENT_MISMATCH"
    REPOSITORY_LIMIT_OR_PAGINATION = "REPOSITORY_LIMIT_OR_PAGINATION"
    BUILDER_LOOKBACK_DEFECT = "BUILDER_LOOKBACK_DEFECT"
    EXPECTED_EARLY_HISTORY_LIMITATION = "EXPECTED_EARLY_HISTORY_LIMITATION"
    UNDETERMINED = "UNDETERMINED"


class ProxySuitability(StrEnum):
    SUITABLE_FOR_CURRENT_DIAGNOSTIC_USE = "SUITABLE_FOR_CURRENT_DIAGNOSTIC_USE"
    SUITABLE_WITH_LIMITATIONS = "SUITABLE_WITH_LIMITATIONS"
    CORPORATE_ACTION_ADJUSTMENT_REQUIRED = "CORPORATE_ACTION_ADJUSTMENT_REQUIRED"
    INDEX_SOURCE_PREFERRED_FOR_BACKFILL = "INDEX_SOURCE_PREFERRED_FOR_BACKFILL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class HistoricalInputReadiness(StrEnum):
    AUTHORITATIVE_SOURCE_READY = "AUTHORITATIVE_SOURCE_READY"
    POINT_IN_TIME_RECONSTRUCTABLE = "POINT_IN_TIME_RECONSTRUCTABLE"
    RECONSTRUCTABLE_WITH_LIMITATIONS = "RECONSTRUCTABLE_WITH_LIMITATIONS"
    TRANSIENT_ONLY = "TRANSIENT_ONLY"
    NO_HISTORICAL_SOURCE = "NO_HISTORICAL_SOURCE"
    SOURCE_NOT_POINT_IN_TIME_SAFE = "SOURCE_NOT_POINT_IN_TIME_SAFE"
    DEFINITION_NOT_VERSIONED = "DEFINITION_NOT_VERSIONED"


class HistoricalSectorReadiness(StrEnum):
    POINT_IN_TIME_SECTOR_HISTORY_READY = "POINT_IN_TIME_SECTOR_HISTORY_READY"
    CURRENT_MAPPING_ONLY = "CURRENT_MAPPING_ONLY"
    PARTIAL_HISTORICAL_MAPPING = "PARTIAL_HISTORICAL_MAPPING"
    SECTOR_INDEX_HISTORY_READY = "SECTOR_INDEX_HISTORY_READY"
    SECTOR_STATE_NOT_RECONSTRUCTABLE = "SECTOR_STATE_NOT_RECONSTRUCTABLE"


class ClassifierVersionReadiness(StrEnum):
    EXACT_CLASSIFIER_VERSION = "EXACT_CLASSIFIER_VERSION"
    COMPATIBLE_CURRENT_VERSION = "COMPATIBLE_CURRENT_VERSION"
    VERSION_UNKNOWN = "VERSION_UNKNOWN"
    KNOWN_DIFFERENT_VERSION = "KNOWN_DIFFERENT_VERSION"
    CLASSIFIER_NOT_REPLAYABLE = "CLASSIFIER_NOT_REPLAYABLE"


class HistoricalBackfillStatus(StrEnum):
    READY_COMPLETE = "READY_COMPLETE"
    READY_PARTIAL = "READY_PARTIAL"
    READY_MINIMUM_VIABLE = "READY_MINIMUM_VIABLE"
    BLOCKED_BENCHMARK = "BLOCKED_BENCHMARK"
    BLOCKED_BREADTH = "BLOCKED_BREADTH"
    BLOCKED_SECTOR = "BLOCKED_SECTOR"
    BLOCKED_TIMESTAMP = "BLOCKED_TIMESTAMP"
    BLOCKED_SOURCE_INTEGRITY = "BLOCKED_SOURCE_INTEGRITY"
    BLOCKED_CLASSIFIER_VERSION = "BLOCKED_CLASSIFIER_VERSION"
    BLOCKED_MULTIPLE_REASONS = "BLOCKED_MULTIPLE_REASONS"


class HistoricalAuthoritativeStatus(StrEnum):
    PRODUCTION_CAPTURED_AUTHORITATIVE = "PRODUCTION_CAPTURED_AUTHORITATIVE"
    SOURCE_REBUILT_AUTHORITATIVE = "SOURCE_REBUILT_AUTHORITATIVE"
    DIAGNOSTIC_RECONSTRUCTED = "DIAGNOSTIC_RECONSTRUCTED"
    PARTIAL_RECONSTRUCTED = "PARTIAL_RECONSTRUCTED"
    UNAVAILABLE = "UNAVAILABLE"


class HistoricalBackfillConclusion(StrEnum):
    HISTORICAL_BACKFILL_READY = "HISTORICAL_BACKFILL_READY"
    HISTORICAL_BACKFILL_READY_FOR_PARTIAL_SNAPSHOTS = (
        "HISTORICAL_BACKFILL_READY_FOR_PARTIAL_SNAPSHOTS"
    )
    BENCHMARK_HISTORY_IS_SUFFICIENT = "BENCHMARK_HISTORY_IS_SUFFICIENT"
    BENCHMARK_HISTORY_QUERY_PATH_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_HISTORY_QUERY_PATH_IS_PRIMARY_BOTTLENECK"
    )
    BENCHMARK_HISTORY_START_DATE_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_HISTORY_START_DATE_IS_PRIMARY_BOTTLENECK"
    )
    BENCHMARK_SOURCE_QUALITY_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_SOURCE_QUALITY_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_BREADTH_SOURCE_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_BREADTH_SOURCE_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_SECTOR_SOURCE_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_SECTOR_SOURCE_IS_PRIMARY_BOTTLENECK"
    )
    CLASSIFIER_VERSION_LINEAGE_IS_PRIMARY_BOTTLENECK = (
        "CLASSIFIER_VERSION_LINEAGE_IS_PRIMARY_BOTTLENECK"
    )
    POINT_IN_TIME_MARKET_UNIVERSE_IS_PRIMARY_BOTTLENECK = (
        "POINT_IN_TIME_MARKET_UNIVERSE_IS_PRIMARY_BOTTLENECK"
    )
    MULTIPLE_HISTORICAL_SOURCES_ARE_INSUFFICIENT = (
        "MULTIPLE_HISTORICAL_SOURCES_ARE_INSUFFICIENT"
    )
    INSUFFICIENT_EVIDENCE_FOR_BACKFILL_READINESS = (
        "INSUFFICIENT_EVIDENCE_FOR_BACKFILL_READINESS"
    )


class HistoricalBackfillNextMilestone(StrEnum):
    EXECUTE_AUTHORITATIVE_MARKET_STATE_BACKFILL = (
        "EXECUTE_AUTHORITATIVE_MARKET_STATE_BACKFILL"
    )
    DESIGN_PARTIAL_MARKET_STATE_BACKFILL = "DESIGN_PARTIAL_MARKET_STATE_BACKFILL"
    REPAIR_BENCHMARK_HISTORY_QUERY = "REPAIR_BENCHMARK_HISTORY_QUERY"
    EXPAND_BENCHMARK_HISTORY = "EXPAND_BENCHMARK_HISTORY"
    BUILD_POINT_IN_TIME_BREADTH_HISTORY = "BUILD_POINT_IN_TIME_BREADTH_HISTORY"
    BUILD_POINT_IN_TIME_SECTOR_HISTORY = "BUILD_POINT_IN_TIME_SECTOR_HISTORY"
    ADD_CLASSIFIER_VERSION_LINEAGE = "ADD_CLASSIFIER_VERSION_LINEAGE"
    BUILD_HISTORICAL_MARKET_UNIVERSE = "BUILD_HISTORICAL_MARKET_UNIVERSE"
    REPAIR_BENCHMARK_SOURCE_DATA = "REPAIR_BENCHMARK_SOURCE_DATA"
    COLLECT_MORE_SOURCE_EVIDENCE = "COLLECT_MORE_SOURCE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class BenchmarkDateReconciliationRow:
    market_date: date
    candidate_count: int
    latest_benchmark_bar: date | None
    calendar_days_since_latest_bar: int | None
    trading_sessions_since_latest_bar: int | None
    alignment: BenchmarkDateAlignment
    bars_available: int
    benchmark_close_available: bool
    return_20d_available: bool
    dma_20_available: bool
    dma_50_available: bool
    dma_200_available: bool
    atr_available: bool
    volatility_available: bool
    completeness: str
    blocking_reason: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkLookbackGapAttribution:
    market_date: date
    candidate_count: int
    bars_available: int
    required_bars: int
    first_benchmark_date: date | None
    first_200dma_ready_date: date | None
    reason: BenchmarkLookbackGapReason
    explanation: str


@dataclass(frozen=True, slots=True)
class BenchmarkSourceIntegrityReport:
    provider_symbol: str
    source_table: str
    row_count_raw: int
    row_count_valid: int
    unique_dates: int
    duplicate_date_count: int
    invalid_ohlc_count: int
    nonpositive_close_count: int
    missing_weekday_session_count: int
    large_gap_count: int
    first_available_date: date | None
    last_available_date: date | None
    first_20dma_ready_date: date | None
    first_50dma_ready_date: date | None
    first_200dma_ready_date: date | None
    integrity_status: str
    explanation: str


@dataclass(frozen=True, slots=True)
class BenchmarkProxySuitabilityReport:
    provider_symbol: str
    logical_name: str
    asset_type: str
    suitability: ProxySuitability
    limitations: tuple[str, ...]
    acceptable_for_diagnostic_backfill: bool
    acceptable_for_authoritative_backfill: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalMarketInputInventoryItem:
    input_name: str
    source: str
    readiness: HistoricalInputReadiness
    date_coverage_count: int
    point_in_time_safe: bool
    versioned_definition: bool
    missing_reason: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class HistoricalBreadthReadinessReport:
    readiness: HistoricalInputReadiness
    candidate_dates_checked: int
    dates_with_price_universe: int
    minimum_symbols_on_date: int
    median_symbols_on_date: int
    survivorship_bias_risk: str
    reconstructable_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorReadinessReport:
    readiness: HistoricalSectorReadiness
    candidate_dates_checked: int
    dates_with_sector_values: int
    sector_history_source: str
    point_in_time_safe: bool
    missing_fields: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class ClassifierVersionReadinessReport:
    readiness: ClassifierVersionReadiness
    records_checked: int
    records_with_classifier_version: int
    records_missing_classifier_version: int
    versions_seen: tuple[tuple[str, int], ...]
    replay_safe: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateBackfillRequest:
    start_date: date | None
    end_date: date | None
    dry_run: bool
    group_by: str | None
    benchmark_symbol: str
    minimum_benchmark_bars: int


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateBackfillRow:
    market_date: date
    candidate_count: int
    expected_completeness: str
    expected_authoritative_status: HistoricalAuthoritativeStatus
    backfill_status: HistoricalBackfillStatus
    benchmark_latest_bar: date | None
    benchmark_bars_available: int
    benchmark_200dma_available: bool
    breadth_reconstructable: bool
    sector_reconstructable: bool
    classifier_replay_available: bool
    expected_missing_fields: tuple[str, ...]
    would_create_snapshot: bool
    expected_regime: str
    source_lineage: tuple[str, ...]
    explanation: str
    historical_classifier_version: str | None = None
    current_replay_classifier_version: str | None = None
    historical_fingerprint: str | None = None
    current_fingerprint: str | None = None
    compatibility_classification: str | None = None
    evidence_strength: str | None = None
    authoritative_eligibility: str | None = None
    version_blocking_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateBackfillSummary:
    candidate_dates: int
    candidate_records: int
    ready_complete_dates: int
    ready_partial_dates: int
    blocked_dates: int
    benchmark_ready_dates: int
    breadth_ready_dates: int
    sector_ready_dates: int
    classifier_ready_dates: int
    counterfactual_200dma_ready_dates: int


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateBackfillPlan:
    rows: tuple[HistoricalMarketStateBackfillRow, ...]
    summary: HistoricalMarketStateBackfillSummary
    dry_run: bool
    no_write_guarantee: str


@dataclass(frozen=True, slots=True)
class CounterfactualCoverageRow:
    market_date: date
    current_completeness: str
    completeness_if_200dma_available: str
    missing_fields: tuple[str, ...]
    fields_unblocked_by_200dma: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateBackfillReadinessReport:
    request: HistoricalMarketStateBackfillRequest
    source_integrity: BenchmarkSourceIntegrityReport
    proxy_suitability: BenchmarkProxySuitabilityReport
    date_reconciliation: tuple[BenchmarkDateReconciliationRow, ...]
    lookback_gaps: tuple[BenchmarkLookbackGapAttribution, ...]
    input_inventory: tuple[HistoricalMarketInputInventoryItem, ...]
    breadth_readiness: HistoricalBreadthReadinessReport
    sector_readiness: HistoricalSectorReadinessReport
    classifier_version_readiness: ClassifierVersionReadinessReport
    simulation_plan: HistoricalMarketStateBackfillPlan
    counterfactual_coverage: tuple[CounterfactualCoverageRow, ...]
    primary_conclusion: HistoricalBackfillConclusion
    secondary_conclusions: tuple[HistoricalBackfillConclusion, ...]
    recommended_next_milestone: HistoricalBackfillNextMilestone
    prohibited_next_action: str


class HistoricalMarketStateBackfillReadinessEngine:
    def __init__(
        self,
        *,
        configuration: BenchmarkConfiguration | None = None,
        stale_days: int = 5,
    ) -> None:
        self.configuration = configuration or canonical_benchmark_configuration()
        self.stale_days = stale_days

    def analyze(
        self,
        *,
        records: tuple[Any, ...],
        price_repository: Any,
        group_by: str | None = None,
    ) -> HistoricalMarketStateBackfillReadinessReport:
        dates = tuple(sorted({record.evaluation_date for record in records}))
        end_date = max(dates) if dates else date.today()
        raw_history = price_repository.find_history_by_symbols(
            symbols=(self.configuration.provider_symbol,),
            end_date=end_date,
            limit=5000,
        )
        history = _prepare_history(
            raw_history,
            provider_symbol=self.configuration.provider_symbol,
        )
        by_date = _records_by_date(records)
        integrity = _source_integrity(
            raw_history=raw_history,
            history=history,
            configuration=self.configuration,
        )
        reconciliation = tuple(
            self._reconcile_date(item, len(by_date.get(item, ())), history)
            for item in dates
        )
        gaps = _lookback_gaps(
            reconciliation=reconciliation,
            history=history,
            integrity=integrity,
        )
        breadth = _breadth_readiness(
            price_repository=price_repository,
            candidate_dates=dates,
        )
        sector = _sector_readiness(
            price_repository=price_repository,
            candidate_dates=dates,
        )
        classifier = _classifier_version_readiness(records)
        inventory = _input_inventory(
            dates=dates,
            reconciliation=reconciliation,
            breadth=breadth,
            sector=sector,
            classifier=classifier,
        )
        proxy = _proxy_suitability(self.configuration)
        simulation = _simulation_plan(
            reconciliation=reconciliation,
            breadth=breadth,
            sector=sector,
            classifier=classifier,
            records_by_date=by_date,
        )
        counterfactuals = _counterfactual_coverage(reconciliation)
        conclusion, secondary, milestone = _conclusion(
            integrity=integrity,
            reconciliation=reconciliation,
            gaps=gaps,
            breadth=breadth,
            sector=sector,
            classifier=classifier,
            simulation=simulation,
        )
        return HistoricalMarketStateBackfillReadinessReport(
            request=HistoricalMarketStateBackfillRequest(
                start_date=min(dates) if dates else None,
                end_date=max(dates) if dates else None,
                dry_run=True,
                group_by=group_by,
                benchmark_symbol=self.configuration.provider_symbol,
                minimum_benchmark_bars=self.configuration.minimum_history_bars,
            ),
            source_integrity=integrity,
            proxy_suitability=proxy,
            date_reconciliation=reconciliation,
            lookback_gaps=gaps,
            input_inventory=inventory,
            breadth_readiness=breadth,
            sector_readiness=sector,
            classifier_version_readiness=classifier,
            simulation_plan=simulation,
            counterfactual_coverage=counterfactuals,
            primary_conclusion=conclusion,
            secondary_conclusions=secondary,
            recommended_next_milestone=milestone,
            prohibited_next_action=(
                "Do not write historical authoritative snapshots, attach "
                "snapshot IDs to historical candidates, relabel candidates, "
                "retune classifier thresholds, alter gates, or change allocation "
                "from this diagnostic report."
            ),
        )

    def _reconcile_date(
        self,
        market_date: date,
        candidate_count: int,
        history: pd.DataFrame,
    ) -> BenchmarkDateReconciliationRow:
        if history.empty:
            return BenchmarkDateReconciliationRow(
                market_date=market_date,
                candidate_count=candidate_count,
                latest_benchmark_bar=None,
                calendar_days_since_latest_bar=None,
                trading_sessions_since_latest_bar=None,
                alignment=BenchmarkDateAlignment.NO_BAR_AT_OR_BEFORE_DATE,
                bars_available=0,
                benchmark_close_available=False,
                return_20d_available=False,
                dma_20_available=False,
                dma_50_available=False,
                dma_200_available=False,
                atr_available=False,
                volatility_available=False,
                completeness=BenchmarkFeatureCompleteness.UNAVAILABLE.value,
                blocking_reason="benchmark history unavailable",
            )
        first_date = history["trade_date"].iloc[0]
        if market_date < first_date:
            alignment = BenchmarkDateAlignment.DATE_BEFORE_BENCHMARK_HISTORY
        else:
            eligible = history[history["trade_date"] <= market_date]
            if eligible.empty:
                alignment = BenchmarkDateAlignment.NO_BAR_AT_OR_BEFORE_DATE
            else:
                latest = eligible["trade_date"].iloc[-1]
                alignment = _alignment_for(market_date, latest, self.stale_days)
        state = BenchmarkStateBuilder(configuration=self.configuration).build(
            bars=history[history["trade_date"] <= market_date],
            decision_as_of=datetime.combine(
                market_date, datetime.max.time(), tzinfo=UTC
            ),
        )
        latest_date = (
            None
            if state.latest_bar_timestamp is None
            else state.latest_bar_timestamp.date()
        )
        calendar_days = (
            None if latest_date is None else max((market_date - latest_date).days, 0)
        )
        return BenchmarkDateReconciliationRow(
            market_date=market_date,
            candidate_count=candidate_count,
            latest_benchmark_bar=latest_date,
            calendar_days_since_latest_bar=calendar_days,
            trading_sessions_since_latest_bar=(
                None
                if latest_date is None
                else _business_days_between(latest_date, market_date)
            ),
            alignment=alignment,
            bars_available=state.bars_available,
            benchmark_close_available=state.benchmark_close is not None,
            return_20d_available=state.benchmark_return_20d is not None,
            dma_20_available=state.benchmark_dma_20 is not None,
            dma_50_available=state.benchmark_dma_50 is not None,
            dma_200_available=state.benchmark_dma_200 is not None,
            atr_available=state.benchmark_atr_14 is not None,
            volatility_available=state.benchmark_volatility is not None,
            completeness=state.completeness.value,
            blocking_reason=_blocking_reason(state.completeness.value, alignment),
        )


def render_backfill_readiness_report(
    report: HistoricalMarketStateBackfillReadinessReport,
    *,
    group_by: str | None = None,
) -> tuple[str, ...]:
    lines = [
        "Historical Market-State Backfill Readiness",
        f"Candidate Dates: {report.simulation_plan.summary.candidate_dates}",
        f"Candidate Records: {report.simulation_plan.summary.candidate_records}",
        f"Benchmark: {report.request.benchmark_symbol}",
        (
            f"Date Range: {_date_text(report.request.start_date)} to "
            f"{_date_text(report.request.end_date)}"
        ),
        f"Dry Run: {'yes' if report.request.dry_run else 'no'}",
        "",
        "Readiness Summary",
        (
            "- Ready Complete Dates: "
            f"{report.simulation_plan.summary.ready_complete_dates}"
        ),
        f"- Ready Partial Dates: {report.simulation_plan.summary.ready_partial_dates}",
        f"- Blocked Dates: {report.simulation_plan.summary.blocked_dates}",
        (
            "- Benchmark Ready Dates: "
            f"{report.simulation_plan.summary.benchmark_ready_dates}"
        ),
        f"- Breadth Ready Dates: {report.simulation_plan.summary.breadth_ready_dates}",
        f"- Sector Ready Dates: {report.simulation_plan.summary.sector_ready_dates}",
        (
            "- Classifier Ready Dates: "
            f"{report.simulation_plan.summary.classifier_ready_dates}"
        ),
        "",
        "Primary Conclusion",
        f"- {report.primary_conclusion.value}",
        "Secondary Conclusions",
        f"- {_enum_list(report.secondary_conclusions)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        f"Explicitly Prohibited Next Action: {report.prohibited_next_action}",
    ]
    if group_by == "date":
        lines.extend(
            ("", *render_benchmark_date_reconciliation(report.date_reconciliation))
        )
    elif group_by == "year":
        lines.extend(("", *_render_year_group(report.simulation_plan.rows)))
    return tuple(lines)


def render_benchmark_date_reconciliation(
    rows: tuple[BenchmarkDateReconciliationRow, ...],
) -> tuple[str, ...]:
    lines = ["Benchmark Date Reconciliation"]
    for row in rows[:200]:
        lines.append(
            "- "
            f"{row.market_date.isoformat()}: candidates={row.candidate_count}, "
            f"latest_bar={_date_text(row.latest_benchmark_bar)}, "
            f"alignment={row.alignment.value}, bars={row.bars_available}, "
            f"200-DMA={'yes' if row.dma_200_available else 'no'}, "
            f"completeness={row.completeness}"
        )
    if len(rows) > 200:
        lines.append(f"- ... {len(rows) - 200} additional dates omitted")
    return tuple(lines)


def render_benchmark_lookback_gaps(
    rows: tuple[BenchmarkLookbackGapAttribution, ...],
) -> tuple[str, ...]:
    lines = ["Benchmark 200-DMA Lookback Gap Attribution"]
    if not rows:
        lines.append("- No benchmark 200-DMA gaps found.")
        return tuple(lines)
    for row in rows[:200]:
        lines.append(
            "- "
            f"{row.market_date.isoformat()}: bars={row.bars_available}/"
            f"{row.required_bars}, reason={row.reason.value}, {row.explanation}"
        )
    if len(rows) > 200:
        lines.append(f"- ... {len(rows) - 200} additional gaps omitted")
    return tuple(lines)


def render_benchmark_source_integrity(
    report: BenchmarkSourceIntegrityReport,
) -> tuple[str, ...]:
    return (
        "Benchmark Source Integrity",
        f"Provider Symbol: {report.provider_symbol}",
        f"Source Table: {report.source_table}",
        f"Raw Rows: {report.row_count_raw}",
        f"Valid Rows: {report.row_count_valid}",
        f"Unique Dates: {report.unique_dates}",
        f"Duplicate Dates: {report.duplicate_date_count}",
        f"Invalid OHLC Rows: {report.invalid_ohlc_count}",
        f"Nonpositive Close Rows: {report.nonpositive_close_count}",
        f"Missing Weekday Sessions: {report.missing_weekday_session_count}",
        f"Large Date Gaps: {report.large_gap_count}",
        f"First Date: {_date_text(report.first_available_date)}",
        f"Last Date: {_date_text(report.last_available_date)}",
        f"First 200-DMA Ready Date: {_date_text(report.first_200dma_ready_date)}",
        f"Status: {report.integrity_status}",
        f"Explanation: {report.explanation}",
    )


def render_benchmark_proxy_suitability(
    report: BenchmarkProxySuitabilityReport,
) -> tuple[str, ...]:
    diagnostic_status = (
        "acceptable" if report.acceptable_for_diagnostic_backfill else "not acceptable"
    )
    authoritative_status = (
        "acceptable"
        if report.acceptable_for_authoritative_backfill
        else "not acceptable"
    )
    return (
        "Benchmark Proxy Suitability",
        f"Provider Symbol: {report.provider_symbol}",
        f"Logical Name: {report.logical_name}",
        f"Asset Type: {report.asset_type}",
        f"Suitability: {report.suitability.value}",
        f"Diagnostic Backfill: {diagnostic_status}",
        f"Authoritative Backfill: {authoritative_status}",
        f"Limitations: {_text_list(report.limitations)}",
        f"Explanation: {report.explanation}",
    )


def render_market_input_inventory(
    items: tuple[HistoricalMarketInputInventoryItem, ...],
) -> tuple[str, ...]:
    lines = ["Historical Market-Input Inventory"]
    for item in items:
        lines.append(
            "- "
            f"{item.input_name}: {item.readiness.value}; source={item.source}; "
            f"coverage={item.date_coverage_count}; point_in_time="
            f"{'yes' if item.point_in_time_safe else 'no'}; {item.notes}"
        )
    return tuple(lines)


def render_historical_breadth_readiness(
    report: HistoricalBreadthReadinessReport,
) -> tuple[str, ...]:
    return (
        "Historical Breadth Readiness",
        f"Readiness: {report.readiness.value}",
        f"Candidate Dates Checked: {report.candidate_dates_checked}",
        f"Dates With Price Universe: {report.dates_with_price_universe}",
        f"Minimum Symbols On Date: {report.minimum_symbols_on_date}",
        f"Median Symbols On Date: {report.median_symbols_on_date}",
        f"Survivorship Bias Risk: {report.survivorship_bias_risk}",
        f"Reconstructable Fields: {_text_list(report.reconstructable_fields)}",
        f"Missing Fields: {_text_list(report.missing_fields)}",
        f"Explanation: {report.explanation}",
    )


def render_historical_sector_readiness(
    report: HistoricalSectorReadinessReport,
) -> tuple[str, ...]:
    return (
        "Historical Sector Readiness",
        f"Readiness: {report.readiness.value}",
        f"Candidate Dates Checked: {report.candidate_dates_checked}",
        f"Dates With Sector Values: {report.dates_with_sector_values}",
        f"Sector History Source: {report.sector_history_source}",
        f"Point-in-Time Safe: {'yes' if report.point_in_time_safe else 'no'}",
        f"Missing Fields: {_text_list(report.missing_fields)}",
        f"Explanation: {report.explanation}",
    )


def render_classifier_version_readiness(
    report: ClassifierVersionReadinessReport,
) -> tuple[str, ...]:
    return (
        "Classifier Version Readiness",
        f"Readiness: {report.readiness.value}",
        f"Records Checked: {report.records_checked}",
        f"Records With Version: {report.records_with_classifier_version}",
        f"Records Missing Version: {report.records_missing_classifier_version}",
        f"Versions Seen: {_pairs(report.versions_seen)}",
        f"Replay Safe: {'yes' if report.replay_safe else 'no'}",
        f"Explanation: {report.explanation}",
    )


def render_market_state_backfill_simulation(
    plan: HistoricalMarketStateBackfillPlan,
) -> tuple[str, ...]:
    lines = [
        "Historical Market-State Backfill Simulation",
        f"Dry Run: {'yes' if plan.dry_run else 'no'}",
        f"No-Write Guarantee: {plan.no_write_guarantee}",
        f"Candidate Dates: {plan.summary.candidate_dates}",
        f"Ready Complete: {plan.summary.ready_complete_dates}",
        f"Ready Partial: {plan.summary.ready_partial_dates}",
        f"Blocked: {plan.summary.blocked_dates}",
        "",
        "Simulated Rows",
    ]
    for row in plan.rows[:200]:
        lines.append(
            "- "
            f"{row.market_date.isoformat()}: candidates={row.candidate_count}, "
            f"status={row.backfill_status.value}, completeness="
            f"{row.expected_completeness}, would_create="
            f"{'yes' if row.would_create_snapshot else 'no'}, "
            f"missing={_text_list(row.expected_missing_fields)}, "
            f"version_eligibility={row.authoritative_eligibility or 'unavailable'}"
        )
    if len(plan.rows) > 200:
        lines.append(f"- ... {len(plan.rows) - 200} additional rows omitted")
    return tuple(lines)


def export_backfill_readiness_json(
    report: HistoricalMarketStateBackfillReadinessReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")
    return path


def export_backfill_readiness_csv(
    report: HistoricalMarketStateBackfillReadinessReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = (
            tuple(_jsonable(report.date_reconciliation[0]).keys())
            if report.date_reconciliation
            else ("market_date",)
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.date_reconciliation:
            writer.writerow(_jsonable(row))
    return path


def _records_by_date(records: tuple[Any, ...]) -> dict[date, tuple[Any, ...]]:
    grouped: dict[date, list[Any]] = {}
    for record in records:
        grouped.setdefault(record.evaluation_date, []).append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def _prepare_history(frame: pd.DataFrame, *, provider_symbol: str) -> pd.DataFrame:
    columns = (
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sector",
        "exchange",
    )
    if frame.empty:
        return pd.DataFrame(columns=columns)
    data = frame.copy()
    data["symbol"] = data["symbol"].astype(str).str.strip().str.upper()
    data = data[data["symbol"] == provider_symbol.strip().upper()]
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    data = data[
        (data["open"] > 0)
        & (data["high"] > 0)
        & (data["low"] > 0)
        & (data["close"] > 0)
    ]
    data = data.drop_duplicates(subset=["trade_date"], keep="last")
    return data.sort_values("trade_date").reset_index(drop=True)


def _source_integrity(
    *,
    raw_history: pd.DataFrame,
    history: pd.DataFrame,
    configuration: BenchmarkConfiguration,
) -> BenchmarkSourceIntegrityReport:
    if raw_history.empty:
        return BenchmarkSourceIntegrityReport(
            provider_symbol=configuration.provider_symbol,
            source_table="daily_prices",
            row_count_raw=0,
            row_count_valid=0,
            unique_dates=0,
            duplicate_date_count=0,
            invalid_ohlc_count=0,
            nonpositive_close_count=0,
            missing_weekday_session_count=0,
            large_gap_count=0,
            first_available_date=None,
            last_available_date=None,
            first_20dma_ready_date=None,
            first_50dma_ready_date=None,
            first_200dma_ready_date=None,
            integrity_status="NO_HISTORY",
            explanation="No benchmark bars were found in daily_prices.",
        )
    raw = raw_history.copy()
    raw["symbol"] = raw["symbol"].astype(str).str.strip().str.upper()
    raw = raw[raw["symbol"] == configuration.provider_symbol]
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    invalid = raw[["open", "high", "low", "close"]].isna().any(axis=1)
    nonpositive = raw["close"].fillna(-1).astype(float) <= 0
    invalid_ohlc = (
        invalid
        | (raw["high"] < raw["low"])
        | (raw["open"] > raw["high"])
        | (raw["open"] < raw["low"])
        | (raw["close"] > raw["high"])
        | (raw["close"] < raw["low"])
    )
    dates = tuple(history["trade_date"].tolist()) if not history.empty else ()
    duplicate_count = int(raw.duplicated(subset=["trade_date"]).sum())
    status = (
        "PASS"
        if len(history) > 0 and int(invalid_ohlc.sum()) == 0
        else "REVIEW_REQUIRED"
    )
    return BenchmarkSourceIntegrityReport(
        provider_symbol=configuration.provider_symbol,
        source_table="daily_prices",
        row_count_raw=len(raw),
        row_count_valid=len(history),
        unique_dates=len(set(dates)),
        duplicate_date_count=duplicate_count,
        invalid_ohlc_count=int(invalid_ohlc.sum()),
        nonpositive_close_count=int(nonpositive.sum()),
        missing_weekday_session_count=_missing_weekdays(dates),
        large_gap_count=_large_gap_count(dates),
        first_available_date=min(dates) if dates else None,
        last_available_date=max(dates) if dates else None,
        first_20dma_ready_date=_nth_date(dates, 20),
        first_50dma_ready_date=_nth_date(dates, 50),
        first_200dma_ready_date=_nth_date(dates, 200),
        integrity_status=status,
        explanation=(
            "Benchmark history is internally usable for deterministic diagnostics."
            if status == "PASS"
            else (
                "Benchmark history has missing or invalid OHLC data that "
                "must be reviewed."
            )
        ),
    )


def _lookback_gaps(
    *,
    reconciliation: tuple[BenchmarkDateReconciliationRow, ...],
    history: pd.DataFrame,
    integrity: BenchmarkSourceIntegrityReport,
) -> tuple[BenchmarkLookbackGapAttribution, ...]:
    gaps: list[BenchmarkLookbackGapAttribution] = []
    first_200 = integrity.first_200dma_ready_date
    for row in reconciliation:
        if row.dma_200_available:
            continue
        if row.bars_available < 200:
            reason = (
                BenchmarkLookbackGapReason.EXPECTED_EARLY_HISTORY_LIMITATION
                if first_200 is not None and row.market_date < first_200
                else BenchmarkLookbackGapReason.FEWER_THAN_200_PRIOR_BARS
            )
        elif integrity.invalid_ohlc_count > 0 or integrity.nonpositive_close_count > 0:
            reason = BenchmarkLookbackGapReason.INVALID_OR_NONFINITE_CLOSES
        elif (
            not history.empty
            and len(history[history["trade_date"] <= row.market_date]) >= 200
        ):
            reason = BenchmarkLookbackGapReason.BUILDER_LOOKBACK_DEFECT
        else:
            reason = BenchmarkLookbackGapReason.UNDETERMINED
        gaps.append(
            BenchmarkLookbackGapAttribution(
                market_date=row.market_date,
                candidate_count=row.candidate_count,
                bars_available=row.bars_available,
                required_bars=200,
                first_benchmark_date=integrity.first_available_date,
                first_200dma_ready_date=first_200,
                reason=reason,
                explanation=_gap_explanation(reason, row, first_200),
            )
        )
    return tuple(gaps)


def _breadth_readiness(
    *,
    price_repository: Any,
    candidate_dates: tuple[date, ...],
) -> HistoricalBreadthReadinessReport:
    counts = []
    for item in candidate_dates:
        try:
            frame = price_repository.find_by_trade_date(item)
        except Exception:
            frame = pd.DataFrame()
        counts.append(0 if frame.empty else int(frame["symbol"].nunique()))
    nonzero = [item for item in counts if item > 0]
    readiness = (
        HistoricalInputReadiness.RECONSTRUCTABLE_WITH_LIMITATIONS
        if nonzero
        else HistoricalInputReadiness.NO_HISTORICAL_SOURCE
    )
    return HistoricalBreadthReadinessReport(
        readiness=readiness,
        candidate_dates_checked=len(candidate_dates),
        dates_with_price_universe=len(nonzero),
        minimum_symbols_on_date=min(nonzero) if nonzero else 0,
        median_symbols_on_date=_median_int(nonzero),
        survivorship_bias_risk="moderate",
        reconstructable_fields=(
            "advancers",
            "decliners",
            "unchanged",
            "percent_above_20dma",
            "percent_above_50dma",
            "percent_above_200dma",
        )
        if nonzero
        else (),
        missing_fields=("point_in_time_index_membership", "authoritative_breadth_feed"),
        explanation=(
            "Daily price rows can reconstruct broad participation with survivorship "
            "and universe-definition limitations."
            if nonzero
            else "No daily price universe was available for candidate dates."
        ),
    )


def _sector_readiness(
    *,
    price_repository: Any,
    candidate_dates: tuple[date, ...],
) -> HistoricalSectorReadinessReport:
    with_sector = 0
    for item in candidate_dates:
        try:
            frame = price_repository.find_by_trade_date(item)
        except Exception:
            frame = pd.DataFrame()
        if not frame.empty and "sector" in frame and frame["sector"].dropna().size > 0:
            with_sector += 1
    return HistoricalSectorReadinessReport(
        readiness=HistoricalSectorReadiness.CURRENT_MAPPING_ONLY,
        candidate_dates_checked=len(candidate_dates),
        dates_with_sector_values=with_sector,
        sector_history_source="daily_prices.sector",
        point_in_time_safe=False,
        missing_fields=("point_in_time_sector_membership", "sector_index_history"),
        explanation=(
            "Sector labels exist in daily price rows but are not proven to be "
            "point-in-time historical classifications."
        ),
    )


def _classifier_version_readiness(
    records: tuple[Any, ...],
) -> ClassifierVersionReadinessReport:
    counts: dict[str, int] = {}
    missing = 0
    for record in records:
        version = getattr(record, "classifier_version", None)
        if version:
            counts[str(version)] = counts.get(str(version), 0) + 1
        else:
            missing += 1
    readiness = (
        ClassifierVersionReadiness.EXACT_CLASSIFIER_VERSION
        if records and missing == 0
        else ClassifierVersionReadiness.VERSION_UNKNOWN
    )
    return ClassifierVersionReadinessReport(
        readiness=readiness,
        records_checked=len(records),
        records_with_classifier_version=len(records) - missing,
        records_missing_classifier_version=missing,
        versions_seen=tuple(sorted(counts.items())),
        replay_safe=readiness is ClassifierVersionReadiness.EXACT_CLASSIFIER_VERSION,
        explanation=(
            "Every candidate record has an explicit classifier version."
            if readiness is ClassifierVersionReadiness.EXACT_CLASSIFIER_VERSION
            else (
                "Some historical candidate rows lack classifier-version lineage, "
                "so exact authoritative replay is unsafe."
            )
        ),
    )


def _input_inventory(
    *,
    dates: tuple[date, ...],
    reconciliation: tuple[BenchmarkDateReconciliationRow, ...],
    breadth: HistoricalBreadthReadinessReport,
    sector: HistoricalSectorReadinessReport,
    classifier: ClassifierVersionReadinessReport,
) -> tuple[HistoricalMarketInputInventoryItem, ...]:
    benchmark_ready = sum(1 for row in reconciliation if row.benchmark_close_available)
    dma200_ready = sum(1 for row in reconciliation if row.dma_200_available)
    return (
        HistoricalMarketInputInventoryItem(
            input_name="benchmark_price_and_returns",
            source="daily_prices/NIFTYBEES",
            readiness=HistoricalInputReadiness.POINT_IN_TIME_RECONSTRUCTABLE,
            date_coverage_count=benchmark_ready,
            point_in_time_safe=True,
            versioned_definition=True,
            missing_reason=None,
            notes="Rebuilt from bars at or before each candidate date.",
        ),
        HistoricalMarketInputInventoryItem(
            input_name="benchmark_200dma",
            source="daily_prices/NIFTYBEES",
            readiness=(
                HistoricalInputReadiness.POINT_IN_TIME_RECONSTRUCTABLE
                if dma200_ready == len(dates)
                else HistoricalInputReadiness.RECONSTRUCTABLE_WITH_LIMITATIONS
            ),
            date_coverage_count=dma200_ready,
            point_in_time_safe=True,
            versioned_definition=True,
            missing_reason=None
            if dma200_ready == len(dates)
            else "requires 200 prior bars",
            notes="Unavailable for early dates before 200 valid benchmark bars exist.",
        ),
        HistoricalMarketInputInventoryItem(
            input_name="market_breadth",
            source="daily_prices/full_date_universe",
            readiness=breadth.readiness,
            date_coverage_count=breadth.dates_with_price_universe,
            point_in_time_safe=False,
            versioned_definition=True,
            missing_reason=None,
            notes=breadth.explanation,
        ),
        HistoricalMarketInputInventoryItem(
            input_name="sector_leadership",
            source=sector.sector_history_source,
            readiness=HistoricalInputReadiness.SOURCE_NOT_POINT_IN_TIME_SAFE,
            date_coverage_count=sector.dates_with_sector_values,
            point_in_time_safe=False,
            versioned_definition=False,
            missing_reason="sector mapping is not proven point-in-time",
            notes=sector.explanation,
        ),
        HistoricalMarketInputInventoryItem(
            input_name="classifier_version",
            source="CandidateDecisionRecord.classifier_version",
            readiness=(
                HistoricalInputReadiness.AUTHORITATIVE_SOURCE_READY
                if classifier.replay_safe
                else HistoricalInputReadiness.DEFINITION_NOT_VERSIONED
            ),
            date_coverage_count=classifier.records_with_classifier_version,
            point_in_time_safe=classifier.replay_safe,
            versioned_definition=classifier.replay_safe,
            missing_reason=None
            if classifier.replay_safe
            else "missing classifier-version lineage",
            notes=classifier.explanation,
        ),
    )


def _proxy_suitability(
    configuration: BenchmarkConfiguration,
) -> BenchmarkProxySuitabilityReport:
    limitations = (
        "NIFTYBEES is an ETF proxy, not the official NIFTY 50 index.",
        (
            "ETF prices can include tracking error, liquidity effects, and "
            "distribution/corporate-action adjustments."
        ),
        (
            "Official index history remains preferred before authoritative "
            "historical backfill."
        ),
    )
    return BenchmarkProxySuitabilityReport(
        provider_symbol=configuration.provider_symbol,
        logical_name=configuration.logical_name,
        asset_type=configuration.asset_type,
        suitability=ProxySuitability.SUITABLE_WITH_LIMITATIONS,
        limitations=limitations,
        acceptable_for_diagnostic_backfill=True,
        acceptable_for_authoritative_backfill=False,
        explanation=(
            "The ETF proxy is acceptable for this diagnostic readiness audit but "
            "should not be renamed or treated as the official NIFTY 50 index."
        ),
    )


def _simulation_plan(
    *,
    reconciliation: tuple[BenchmarkDateReconciliationRow, ...],
    breadth: HistoricalBreadthReadinessReport,
    sector: HistoricalSectorReadinessReport,
    classifier: ClassifierVersionReadinessReport,
    records_by_date: dict[date, tuple[Any, ...]],
) -> HistoricalMarketStateBackfillPlan:
    rows: list[HistoricalMarketStateBackfillRow] = []
    for row in reconciliation:
        version_state = _date_version_state(records_by_date.get(row.market_date, ()))
        missing = []
        if row.completeness in {"UNAVAILABLE", "INSUFFICIENT"}:
            missing.append("benchmark_minimum_features")
        if not row.dma_200_available:
            missing.append("benchmark_200dma")
        if (
            breadth.readiness
            is not HistoricalInputReadiness.RECONSTRUCTABLE_WITH_LIMITATIONS
        ):
            missing.append("market_breadth")
        if (
            sector.readiness
            is not HistoricalSectorReadiness.POINT_IN_TIME_SECTOR_HISTORY_READY
        ):
            missing.append("point_in_time_sector_history")
        if not classifier.replay_safe:
            missing.append("classifier_version")
        benchmark_ready = row.completeness not in {"UNAVAILABLE", "INSUFFICIENT"}
        breadth_ready = breadth.readiness in {
            HistoricalInputReadiness.POINT_IN_TIME_RECONSTRUCTABLE,
            HistoricalInputReadiness.RECONSTRUCTABLE_WITH_LIMITATIONS,
        }
        if not benchmark_ready:
            status = HistoricalBackfillStatus.BLOCKED_BENCHMARK
            authoritative = HistoricalAuthoritativeStatus.UNAVAILABLE
            would_create = False
        elif benchmark_ready and breadth_ready:
            status = HistoricalBackfillStatus.READY_PARTIAL
            authoritative = HistoricalAuthoritativeStatus.PARTIAL_RECONSTRUCTED
            would_create = True
        else:
            status = HistoricalBackfillStatus.BLOCKED_MULTIPLE_REASONS
            authoritative = HistoricalAuthoritativeStatus.UNAVAILABLE
            would_create = False
        rows.append(
            HistoricalMarketStateBackfillRow(
                market_date=row.market_date,
                candidate_count=row.candidate_count,
                expected_completeness="PARTIAL" if would_create else "UNAVAILABLE",
                expected_authoritative_status=authoritative,
                backfill_status=status,
                benchmark_latest_bar=row.latest_benchmark_bar,
                benchmark_bars_available=row.bars_available,
                benchmark_200dma_available=row.dma_200_available,
                breadth_reconstructable=breadth_ready,
                sector_reconstructable=False,
                classifier_replay_available=classifier.replay_safe,
                expected_missing_fields=tuple(missing),
                would_create_snapshot=would_create,
                expected_regime="UNAVAILABLE_UNTIL_CLASSIFIER_REPLAY",
                source_lineage=(
                    "daily_prices",
                    "NIFTYBEES_ETF_PROXY",
                    "diagnostic_dry_run_no_write",
                ),
                explanation=(
                    "Partial diagnostic reconstruction is possible, but this row "
                    "must not be treated as authoritative."
                    if would_create
                    else "Minimum source inputs are not available for reconstruction."
                ),
                historical_classifier_version=version_state["historical_version"],
                current_replay_classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
                historical_fingerprint=version_state["historical_fingerprint"],
                current_fingerprint=current_market_classifier_fingerprint(),
                compatibility_classification=version_state["compatibility"],
                evidence_strength=version_state["evidence_strength"],
                authoritative_eligibility=version_state["eligibility"],
                version_blocking_reason=version_state["blocking_reason"],
            )
        )
    summary = HistoricalMarketStateBackfillSummary(
        candidate_dates=len(rows),
        candidate_records=sum(row.candidate_count for row in rows),
        ready_complete_dates=sum(
            1
            for row in rows
            if row.backfill_status is HistoricalBackfillStatus.READY_COMPLETE
        ),
        ready_partial_dates=sum(
            1
            for row in rows
            if row.backfill_status is HistoricalBackfillStatus.READY_PARTIAL
        ),
        blocked_dates=sum(
            1 for row in rows if row.backfill_status.value.startswith("BLOCKED_")
        ),
        benchmark_ready_dates=sum(
            1
            for row in rows
            if row.backfill_status is not HistoricalBackfillStatus.BLOCKED_BENCHMARK
        ),
        breadth_ready_dates=sum(1 for row in rows if row.breadth_reconstructable),
        sector_ready_dates=sum(1 for row in rows if row.sector_reconstructable),
        classifier_ready_dates=sum(
            1 for row in rows if row.classifier_replay_available
        ),
        counterfactual_200dma_ready_dates=sum(
            1 for row in rows if row.benchmark_200dma_available
        ),
    )
    return HistoricalMarketStateBackfillPlan(
        rows=tuple(rows),
        summary=summary,
        dry_run=True,
        no_write_guarantee=(
            "This simulation only creates in-memory rows and never writes "
            ".alpha/market_state_snapshots.json or candidate records."
        ),
    )


def _counterfactual_coverage(
    reconciliation: tuple[BenchmarkDateReconciliationRow, ...],
) -> tuple[CounterfactualCoverageRow, ...]:
    rows = []
    for row in reconciliation:
        missing = []
        if not row.dma_200_available:
            missing.append("benchmark_200dma")
        rows.append(
            CounterfactualCoverageRow(
                market_date=row.market_date,
                current_completeness=row.completeness,
                completeness_if_200dma_available=(
                    "COMPLETE"
                    if row.completeness == "PARTIAL" and "benchmark_200dma" in missing
                    else row.completeness
                ),
                missing_fields=tuple(missing),
                fields_unblocked_by_200dma=("benchmark_200dma",)
                if "benchmark_200dma" in missing
                else (),
            )
        )
    return tuple(rows)


def _date_version_state(records: tuple[Any, ...]) -> dict[str, str | None]:
    if not records:
        return {
            "historical_version": None,
            "historical_fingerprint": None,
            "compatibility": ComponentCompatibility.VERSION_UNKNOWN.value,
            "evidence_strength": EvidenceReliability.UNUSABLE.value,
            "eligibility": (
                HistoricalBackfillVersionEligibility.BLOCKED_VERSION_UNKNOWN.value
            ),
            "blocking_reason": "no candidate records found for date",
        }
    versions = {
        str(getattr(record, "classifier_version"))
        for record in records
        if getattr(record, "classifier_version", None)
    }
    known_record_count = sum(
        1
        for record in records
        if getattr(record, "classifier_version", None)
        or getattr(record, "decision_provenance_id", None)
    )
    provenance_record_count = sum(
        1 for record in records if getattr(record, "decision_provenance_id", None)
    )
    if known_record_count == 0:
        return {
            "historical_version": None,
            "historical_fingerprint": None,
            "compatibility": ComponentCompatibility.VERSION_UNKNOWN.value,
            "evidence_strength": EvidenceReliability.UNUSABLE.value,
            "eligibility": (
                HistoricalBackfillVersionEligibility.BLOCKED_VERSION_UNKNOWN.value
            ),
            "blocking_reason": (
                "historical classifier version or exact fingerprint is unknown"
            ),
        }
    if known_record_count < len(records):
        return {
            "historical_version": "MIXED_KNOWN_AND_UNKNOWN",
            "historical_fingerprint": "MIXED_KNOWN_AND_UNKNOWN",
            "compatibility": ComponentCompatibility.INSUFFICIENT_EVIDENCE.value,
            "evidence_strength": EvidenceReliability.WEAK.value,
            "eligibility": (
                HistoricalBackfillVersionEligibility.BLOCKED_VERSION_UNKNOWN.value
            ),
            "blocking_reason": (
                "only some candidates on this date have classifier lineage"
            ),
        }
    if provenance_record_count == len(records):
        return {
            "historical_version": "PERSISTED_PROVENANCE_ID",
            "historical_fingerprint": "PERSISTED_PROVENANCE_ID",
            "compatibility": ComponentCompatibility.EXACT_FINGERPRINT_MATCH.value,
            "evidence_strength": EvidenceReliability.AUTHORITATIVE.value,
            "eligibility": (
                HistoricalBackfillVersionEligibility.ELIGIBLE_FINGERPRINT_MATCH.value
            ),
            "blocking_reason": None,
        }
    if versions == {MARKET_STATE_CLASSIFIER_VERSION}:
        return {
            "historical_version": MARKET_STATE_CLASSIFIER_VERSION,
            "historical_fingerprint": None,
            "compatibility": ComponentCompatibility.EXACT_VERSION_MATCH.value,
            "evidence_strength": EvidenceReliability.STRONG.value,
            "eligibility": HistoricalBackfillVersionEligibility.ELIGIBLE_EXACT.value,
            "blocking_reason": None,
        }
    return {
        "historical_version": "CONFLICTING_OR_MIXED",
        "historical_fingerprint": None,
        "compatibility": ComponentCompatibility.INSUFFICIENT_EVIDENCE.value,
        "evidence_strength": EvidenceReliability.WEAK.value,
        "eligibility": (
            HistoricalBackfillVersionEligibility.BLOCKED_VERSION_CONFLICT.value
        ),
        "blocking_reason": "candidate records contain mixed classifier lineage",
    }


def _conclusion(
    *,
    integrity: BenchmarkSourceIntegrityReport,
    reconciliation: tuple[BenchmarkDateReconciliationRow, ...],
    gaps: tuple[BenchmarkLookbackGapAttribution, ...],
    breadth: HistoricalBreadthReadinessReport,
    sector: HistoricalSectorReadinessReport,
    classifier: ClassifierVersionReadinessReport,
    simulation: HistoricalMarketStateBackfillPlan,
) -> tuple[
    HistoricalBackfillConclusion,
    tuple[HistoricalBackfillConclusion, ...],
    HistoricalBackfillNextMilestone,
]:
    if not reconciliation:
        return (
            HistoricalBackfillConclusion.INSUFFICIENT_EVIDENCE_FOR_BACKFILL_READINESS,
            (),
            HistoricalBackfillNextMilestone.COLLECT_MORE_SOURCE_EVIDENCE,
        )
    if integrity.integrity_status != "PASS":
        return (
            HistoricalBackfillConclusion.BENCHMARK_SOURCE_QUALITY_IS_PRIMARY_BOTTLENECK,
            (),
            HistoricalBackfillNextMilestone.REPAIR_BENCHMARK_SOURCE_DATA,
        )
    if any(
        gap.reason is BenchmarkLookbackGapReason.BUILDER_LOOKBACK_DEFECT for gap in gaps
    ):
        return (
            HistoricalBackfillConclusion.BENCHMARK_HISTORY_QUERY_PATH_IS_PRIMARY_BOTTLENECK,
            (),
            HistoricalBackfillNextMilestone.REPAIR_BENCHMARK_HISTORY_QUERY,
        )
    if all(
        row.backfill_status is HistoricalBackfillStatus.BLOCKED_BENCHMARK
        for row in simulation.rows
    ):
        return (
            HistoricalBackfillConclusion.BENCHMARK_HISTORY_START_DATE_IS_PRIMARY_BOTTLENECK,
            (),
            HistoricalBackfillNextMilestone.EXPAND_BENCHMARK_HISTORY,
        )
    secondary: list[HistoricalBackfillConclusion] = []
    if any(
        gap.reason is BenchmarkLookbackGapReason.EXPECTED_EARLY_HISTORY_LIMITATION
        for gap in gaps
    ):
        secondary.append(
            HistoricalBackfillConclusion.BENCHMARK_HISTORY_START_DATE_IS_PRIMARY_BOTTLENECK
        )
    if (
        breadth.readiness
        is not HistoricalInputReadiness.RECONSTRUCTABLE_WITH_LIMITATIONS
    ):
        return (
            HistoricalBackfillConclusion.HISTORICAL_BREADTH_SOURCE_IS_PRIMARY_BOTTLENECK,
            tuple(secondary),
            HistoricalBackfillNextMilestone.BUILD_POINT_IN_TIME_BREADTH_HISTORY,
        )
    if not classifier.replay_safe:
        secondary.append(
            HistoricalBackfillConclusion.HISTORICAL_SECTOR_SOURCE_IS_PRIMARY_BOTTLENECK
        )
        return (
            HistoricalBackfillConclusion.CLASSIFIER_VERSION_LINEAGE_IS_PRIMARY_BOTTLENECK,
            tuple(dict.fromkeys(secondary)),
            HistoricalBackfillNextMilestone.ADD_CLASSIFIER_VERSION_LINEAGE,
        )
    if (
        sector.readiness
        is not HistoricalSectorReadiness.POINT_IN_TIME_SECTOR_HISTORY_READY
    ):
        return (
            HistoricalBackfillConclusion.HISTORICAL_SECTOR_SOURCE_IS_PRIMARY_BOTTLENECK,
            tuple(secondary),
            HistoricalBackfillNextMilestone.BUILD_POINT_IN_TIME_SECTOR_HISTORY,
        )
    if simulation.summary.ready_partial_dates > 0:
        return (
            HistoricalBackfillConclusion.HISTORICAL_BACKFILL_READY_FOR_PARTIAL_SNAPSHOTS,
            tuple(secondary),
            HistoricalBackfillNextMilestone.DESIGN_PARTIAL_MARKET_STATE_BACKFILL,
        )
    return (
        HistoricalBackfillConclusion.HISTORICAL_BACKFILL_READY,
        tuple(secondary),
        HistoricalBackfillNextMilestone.EXECUTE_AUTHORITATIVE_MARKET_STATE_BACKFILL,
    )


def _alignment_for(
    market_date: date, latest: date, stale_days: int
) -> BenchmarkDateAlignment:
    if latest == market_date:
        return BenchmarkDateAlignment.SAME_TRADING_DAY
    days = (market_date - latest).days
    sessions = _business_days_between(latest, market_date)
    if sessions == 1:
        return BenchmarkDateAlignment.PREVIOUS_COMPLETED_SESSION
    if days <= stale_days:
        return BenchmarkDateAlignment.VALID_CARRIED_FORWARD
    return BenchmarkDateAlignment.STALE_CARRIED_FORWARD


def _blocking_reason(
    completeness: str,
    alignment: BenchmarkDateAlignment,
) -> str | None:
    if alignment in {
        BenchmarkDateAlignment.NO_BAR_AT_OR_BEFORE_DATE,
        BenchmarkDateAlignment.DATE_BEFORE_BENCHMARK_HISTORY,
    }:
        return "benchmark bar unavailable at or before candidate date"
    if alignment is BenchmarkDateAlignment.STALE_CARRIED_FORWARD:
        return "benchmark bar is stale for candidate date"
    if completeness in {"UNAVAILABLE", "INSUFFICIENT"}:
        return "benchmark minimum features unavailable"
    return None


def _business_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    current = start + timedelta(days=1)
    count = 0
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _missing_weekdays(dates: tuple[date, ...]) -> int:
    if not dates:
        return 0
    present = set(dates)
    current = min(dates)
    missing = 0
    while current <= max(dates):
        if current.weekday() < 5 and current not in present:
            missing += 1
        current += timedelta(days=1)
    return missing


def _large_gap_count(dates: tuple[date, ...]) -> int:
    return sum(
        1
        for previous, current in zip(dates, dates[1:])
        if (current - previous).days > 7
    )


def _nth_date(dates: tuple[date, ...], count: int) -> date | None:
    return dates[count - 1] if len(dates) >= count else None


def _median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _gap_explanation(
    reason: BenchmarkLookbackGapReason,
    row: BenchmarkDateReconciliationRow,
    first_200: date | None,
) -> str:
    if reason is BenchmarkLookbackGapReason.EXPECTED_EARLY_HISTORY_LIMITATION:
        return (
            f"Only {row.bars_available} benchmark bars existed by this date; "
            f"first 200-DMA-ready date is {_date_text(first_200)}."
        )
    if reason is BenchmarkLookbackGapReason.BUILDER_LOOKBACK_DEFECT:
        return "At least 200 bars are present but the builder did not produce 200-DMA."
    if reason is BenchmarkLookbackGapReason.INVALID_OR_NONFINITE_CLOSES:
        return "Source rows include invalid or nonpositive close values."
    return f"Only {row.bars_available} bars were available for a 200-bar feature."


def _render_year_group(
    rows: tuple[HistoricalMarketStateBackfillRow, ...],
) -> tuple[str, ...]:
    counts: dict[int, dict[str, int]] = {}
    for row in rows:
        bucket = counts.setdefault(
            row.market_date.year, {"total": 0, "partial": 0, "blocked": 0}
        )
        bucket["total"] += 1
        if row.backfill_status is HistoricalBackfillStatus.READY_PARTIAL:
            bucket["partial"] += 1
        if row.backfill_status.value.startswith("BLOCKED_"):
            bucket["blocked"] += 1
    lines = ["Readiness By Year"]
    for year, values in sorted(counts.items()):
        lines.append(
            f"- {year}: dates={values['total']}, "
            f"ready_partial={values['partial']}, blocked={values['blocked']}"
        )
    return tuple(lines)


def _date_text(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _text_list(values: Iterable[str]) -> str:
    return ", ".join(values) if tuple(values) else "none"


def _enum_list(values: Iterable[StrEnum]) -> str:
    items = tuple(value.value for value in values)
    return ", ".join(items) if items else "none"


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) if values else "none"


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


__all__ = [
    "BenchmarkDateAlignment",
    "BenchmarkLookbackGapAttribution",
    "BenchmarkLookbackGapReason",
    "BenchmarkProxySuitabilityReport",
    "BenchmarkSourceIntegrityReport",
    "ClassifierVersionReadiness",
    "ClassifierVersionReadinessReport",
    "HistoricalAuthoritativeStatus",
    "HistoricalBackfillConclusion",
    "HistoricalBackfillNextMilestone",
    "HistoricalBackfillStatus",
    "HistoricalBreadthReadinessReport",
    "HistoricalInputReadiness",
    "HistoricalMarketInputInventoryItem",
    "HistoricalMarketStateBackfillPlan",
    "HistoricalMarketStateBackfillReadinessEngine",
    "HistoricalMarketStateBackfillReadinessReport",
    "HistoricalMarketStateBackfillRequest",
    "HistoricalMarketStateBackfillRow",
    "HistoricalMarketStateBackfillSummary",
    "HistoricalSectorReadiness",
    "HistoricalSectorReadinessReport",
    "ProxySuitability",
    "export_backfill_readiness_csv",
    "export_backfill_readiness_json",
    "render_backfill_readiness_report",
    "render_benchmark_date_reconciliation",
    "render_benchmark_lookback_gaps",
    "render_benchmark_proxy_suitability",
    "render_benchmark_source_integrity",
    "render_classifier_version_readiness",
    "render_historical_breadth_readiness",
    "render_historical_sector_readiness",
    "render_market_input_inventory",
    "render_market_state_backfill_simulation",
]
