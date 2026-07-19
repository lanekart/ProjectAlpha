from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.entry_timing import (
    EntryTimingState,
    build_entry_timing_replay_report,
)
from alpha.candidate_learning.market_regime_audit import (
    CanonicalRegime,
    ReferenceMarketState,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.market_intelligence.snapshots import MarketStateSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")
_POSITIVE_VERDICTS = {"BUY", "STRONG_BUY"}
_PRIMARY_ENTRY_STATES = {
    EntryTimingState.AGGRESSIVE_ENTRY,
    EntryTimingState.PREFERRED_ENTRY,
    EntryTimingState.CONFIRMATION_ENTRY,
}


class MarketStateReconstructionStatus(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    FULLY_RECONSTRUCTED = "FULLY_RECONSTRUCTED"
    PARTIALLY_RECONSTRUCTED = "PARTIALLY_RECONSTRUCTED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_UNIVERSE = "INSUFFICIENT_UNIVERSE"
    BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"
    BREADTH_UNAVAILABLE = "BREADTH_UNAVAILABLE"
    TIMESTAMP_UNAVAILABLE = "TIMESTAMP_UNAVAILABLE"
    RECONSTRUCTION_UNAVAILABLE = "RECONSTRUCTION_UNAVAILABLE"


class MarketStateFeatureStatus(StrEnum):
    PERSISTED_AUTHORITATIVE = "PERSISTED_AUTHORITATIVE"
    PERSISTED_PARTIAL = "PERSISTED_PARTIAL"
    TRANSIENT_ONLY = "TRANSIENT_ONLY"
    RECONSTRUCTABLE_SAME_DATE = "RECONSTRUCTABLE_SAME_DATE"
    RECONSTRUCTABLE_WITH_LIMITATIONS = "RECONSTRUCTABLE_WITH_LIMITATIONS"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class TimestampAlignment(StrEnum):
    AUTHORITATIVE_SNAPSHOT_EXACT = "AUTHORITATIVE_SNAPSHOT_EXACT"
    AUTHORITATIVE_SNAPSHOT_SAME_DAY = "AUTHORITATIVE_SNAPSHOT_SAME_DAY"
    AUTHORITATIVE_SNAPSHOT_STALE = "AUTHORITATIVE_SNAPSHOT_STALE"
    AUTHORITATIVE_SNAPSHOT_FUTURE_INVALID = "AUTHORITATIVE_SNAPSHOT_FUTURE_INVALID"
    SNAPSHOT_ID_MISSING = "SNAPSHOT_ID_MISSING"
    SNAPSHOT_RECORD_MISSING = "SNAPSHOT_RECORD_MISSING"
    LEGACY_CANDIDATE_WITHOUT_SNAPSHOT = "LEGACY_CANDIDATE_WITHOUT_SNAPSHOT"
    EXACT = "EXACT"
    SAME_TRADING_DAY = "SAME_TRADING_DAY"
    CARRIED_FORWARD_VALID = "CARRIED_FORWARD_VALID"
    CARRIED_FORWARD_STALE = "CARRIED_FORWARD_STALE"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
    DEFAULTED_WITHOUT_SOURCE = "DEFAULTED_WITHOUT_SOURCE"
    RECONSTRUCTED_SAME_DATE = "RECONSTRUCTED_SAME_DATE"
    RECONSTRUCTION_UNAVAILABLE = "RECONSTRUCTION_UNAVAILABLE"


class NeutralFallbackReason(StrEnum):
    GENUINE_NEUTRAL_CLASSIFICATION = "GENUINE_NEUTRAL_CLASSIFICATION"
    MISSING_BENCHMARK_INPUT = "MISSING_BENCHMARK_INPUT"
    MISSING_BREADTH_INPUT = "MISSING_BREADTH_INPUT"
    MISSING_VOLATILITY_INPUT = "MISSING_VOLATILITY_INPUT"
    MISSING_SECTOR_INPUT = "MISSING_SECTOR_INPUT"
    INSUFFICIENT_LOOKBACK = "INSUFFICIENT_LOOKBACK"
    STALE_MARKET_STATE = "STALE_MARKET_STATE"
    MISSING_MARKET_STATE_RECORD = "MISSING_MARKET_STATE_RECORD"
    CANDIDATE_ATTACHMENT_MISSING = "CANDIDATE_ATTACHMENT_MISSING"
    REGIME_FIELD_DEFAULT_VALUE = "REGIME_FIELD_DEFAULT_VALUE"
    UNKNOWN_ALIAS_NORMALIZED_TO_NEUTRAL = "UNKNOWN_ALIAS_NORMALIZED_TO_NEUTRAL"
    CLASSIFIER_EXCEPTION_FALLBACK = "CLASSIFIER_EXCEPTION_FALLBACK"
    REPLAY_RECONSTRUCTION_FALLBACK = "REPLAY_RECONSTRUCTION_FALLBACK"
    CANDIDATE_SELECTION_CONCENTRATION = "CANDIDATE_SELECTION_CONCENTRATION"
    UNDETERMINED = "UNDETERMINED"


class MarketEpisodeType(StrEnum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    BREADTH_EXPANSION = "BREADTH_EXPANSION"
    BREADTH_CONTRACTION = "BREADTH_CONTRACTION"
    DISTRIBUTION = "DISTRIBUTION"
    ACCUMULATION = "ACCUMULATION"
    RANGE_BOUND = "RANGE_BOUND"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class ClassifierReplayAgreement(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    DIRECTIONAL_MATCH = "DIRECTIONAL_MATCH"
    NEUTRAL_COLLAPSE = "NEUTRAL_COLLAPSE"
    SIGN_CONFLICT = "SIGN_CONFLICT"
    ORIGINAL_DEFAULTED = "ORIGINAL_DEFAULTED"
    REPLAY_UNAVAILABLE = "REPLAY_UNAVAILABLE"
    INPUT_MISMATCH = "INPUT_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"


class MarketStateConclusion(StrEnum):
    MARKET_STATE_HISTORY_NOT_PERSISTED = "MARKET_STATE_HISTORY_NOT_PERSISTED"
    MARKET_STATE_HISTORY_PARTIALLY_PERSISTED = (
        "MARKET_STATE_HISTORY_PARTIALLY_PERSISTED"
    )
    DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK = (
        "DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK"
    )
    MARKET_STATE_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK = (
        "MARKET_STATE_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK"
    )
    CANDIDATE_REGIME_ATTACHMENT_IS_PRIMARY_BOTTLENECK = (
        "CANDIDATE_REGIME_ATTACHMENT_IS_PRIMARY_BOTTLENECK"
    )
    REPLAY_RECONSTRUCTION_IS_PRIMARY_BOTTLENECK = (
        "REPLAY_RECONSTRUCTION_IS_PRIMARY_BOTTLENECK"
    )
    MARKET_STATE_INPUT_COMPLETENESS_IS_PRIMARY_BOTTLENECK = (
        "MARKET_STATE_INPUT_COMPLETENESS_IS_PRIMARY_BOTTLENECK"
    )
    CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_BOTTLENECK = (
        "CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_BOTTLENECK"
    )
    PRODUCTION_CLASSIFIER_DISAGREES_WITH_RECONSTRUCTION = (
        "PRODUCTION_CLASSIFIER_DISAGREES_WITH_RECONSTRUCTION"
    )
    PRODUCTION_CLASSIFIER_APPEARS_CONSISTENT = (
        "PRODUCTION_CLASSIFIER_APPEARS_CONSISTENT"
    )
    MARKET_STATE_PERSISTENCE_IS_SUFFICIENT = "MARKET_STATE_PERSISTENCE_IS_SUFFICIENT"
    INSUFFICIENT_EVIDENCE_FOR_MARKET_STATE_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_MARKET_STATE_CONCLUSION"
    )


class NextMarketStateMilestone(StrEnum):
    AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN = (
        "AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN"
    )
    HARDEN_MARKET_STATE_CAPTURE = "HARDEN_MARKET_STATE_CAPTURE"
    REPAIR_MARKET_STATE_CANDIDATE_LINKAGE = "REPAIR_MARKET_STATE_CANDIDATE_LINKAGE"
    ADD_AUTHORITATIVE_MARKET_STATE_SNAPSHOTS = (
        "ADD_AUTHORITATIVE_MARKET_STATE_SNAPSHOTS"
    )
    BACKFILL_MARKET_STATE_HISTORY = "BACKFILL_MARKET_STATE_HISTORY"
    ADD_MARKET_STATE_TIMESTAMP_LINKAGE = "ADD_MARKET_STATE_TIMESTAMP_LINKAGE"
    REPAIR_CANDIDATE_REGIME_ATTACHMENT = "REPAIR_CANDIDATE_REGIME_ATTACHMENT"
    ADD_CLASSIFIER_VERSION_PERSISTENCE = "ADD_CLASSIFIER_VERSION_PERSISTENCE"
    EXPAND_MARKET_BREADTH_HISTORY = "EXPAND_MARKET_BREADTH_HISTORY"
    EXPAND_BENCHMARK_HISTORY = "EXPAND_BENCHMARK_HISTORY"
    AUDIT_PRODUCTION_REGIME_THRESHOLDS = "AUDIT_PRODUCTION_REGIME_THRESHOLDS"
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE = (
        "AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE"
    )
    INSUFFICIENT_EVIDENCE_COLLECT_MORE_HISTORY = (
        "INSUFFICIENT_EVIDENCE_COLLECT_MORE_HISTORY"
    )


@dataclass(frozen=True, slots=True)
class MarketStatePersistenceAuditConfig:
    minimum_sample: int = 30
    stale_days: int = 5
    neutral_fallback_threshold: Decimal = Decimal("0.70")


@dataclass(frozen=True, slots=True)
class HistoricalMarketStateSnapshot:
    as_of: str
    market_date: str | None
    source_timestamp: str | None
    benchmark_symbol: str | None
    benchmark_close: Decimal | None
    benchmark_return_1d: Decimal | None
    benchmark_return_5d: Decimal | None
    benchmark_return_20d: Decimal | None
    benchmark_above_20dma: bool | None
    benchmark_above_50dma: bool | None
    benchmark_above_200dma: bool | None
    benchmark_distance_20dma: Decimal | None
    benchmark_distance_50dma: Decimal | None
    benchmark_distance_200dma: Decimal | None
    benchmark_atr: Decimal | None
    benchmark_volatility: Decimal | None
    breadth_advancers: int | None
    breadth_decliners: int | None
    breadth_unchanged: int | None
    breadth_ratio: Decimal | None
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    new_highs: int | None
    new_lows: int | None
    sector_leadership: str | None
    sector_dispersion: Decimal | None
    market_trend_score: Decimal | None
    breadth_score: Decimal | None
    volatility_score: Decimal | None
    participation_score: Decimal | None
    reference_state: ReferenceMarketState
    production_regime: str | None
    production_regime_confidence: Decimal | None
    classifier_version: str | None
    source_completeness: Decimal
    reconstruction_status: MarketStateReconstructionStatus
    missing_fields: tuple[str, ...]
    source_fields_used: tuple[str, ...]
    lookback_bars_available: int
    universe_size: int | None
    benchmark_available: bool
    breadth_available: bool
    sector_data_available: bool
    confidence_or_completeness_grade: str


@dataclass(frozen=True, slots=True)
class PersistenceInventoryItem:
    field: str
    source_model: str
    source_table_file: str
    persisted_or_transient: str
    timestamped_or_untimestamped: str
    candidate_linked_or_market_level: str
    authoritative_or_reconstructed: MarketStateFeatureStatus
    coverage_count: int
    first_date: str | None
    last_date: str | None
    missing_rate: Decimal | None
    notes: str


@dataclass(frozen=True, slots=True)
class TimestampIntegrityFinding:
    candidate_id: str
    symbol: str
    candidate_decision_timestamp: str
    market_state_source_timestamp: str | None
    classifier_timestamp: str | None
    attached_regime_timestamp: str | None
    recommendation_timestamp: str
    replay_timestamp: str
    alignment: TimestampAlignment
    staleness_days: int | None
    completed_outcome: bool
    buy_candidate: bool
    acceptably_timed: bool
    issue: str


@dataclass(frozen=True, slots=True)
class TimestampAlignmentSummary:
    alignment: TimestampAlignment
    count: int
    percentage: Decimal | None
    oldest_example: str | None
    newest_example: str | None
    maximum_staleness_days: int | None
    median_staleness_days: Decimal | None
    completed_outcomes_affected: int
    buy_candidates_affected: int
    acceptably_timed_candidates_affected: int


@dataclass(frozen=True, slots=True)
class FallbackAttribution:
    candidate_id: str
    symbol: str
    market_date: str
    setup_type: str | None
    verdict: str
    entry_state: EntryTimingState
    reference_state: ReferenceMarketState
    primary_reason: NeutralFallbackReason
    secondary_reasons: tuple[NeutralFallbackReason, ...]
    completed_outcome: bool
    profitable: bool | None
    benchmark_relative_outcome: Decimal | None


@dataclass(frozen=True, slots=True)
class FallbackAttributionSummary:
    reason: NeutralFallbackReason
    candidate_count: int
    completed_outcomes: int
    win_rate: Decimal | None
    setup_counts: tuple[tuple[str, int], ...]
    verdict_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class StateComparisonSummary:
    sample_count: int
    exact_regime_agreement: Decimal | None
    directional_agreement: Decimal | None
    neutral_disagreement_rate: Decimal | None
    extreme_to_neutral_collapse_rate: Decimal | None
    balanced_accuracy: Decimal | None
    timestamp_difference_days: Decimal | None
    notes: str


@dataclass(frozen=True, slots=True)
class MarketStateEpisode:
    episode_type: MarketEpisodeType
    start: str
    end: str
    trading_days: int
    candidate_count: int
    buy_count: int
    acceptable_entry_count: int
    win_rate: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    maximum_adverse_excursion: Decimal | None
    maximum_favourable_excursion: Decimal | None
    production_regime_distribution: tuple[tuple[str, int], ...]
    fallback_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CandidateSelectionDistribution:
    stage: str
    sample_count: int
    market_state_distribution: tuple[tuple[str, int], ...]
    neutral_share: Decimal | None
    bearish_reference_share: Decimal | None
    notes: str


@dataclass(frozen=True, slots=True)
class ClassifierReplayResult:
    candidate_id: str
    symbol: str
    original_attached_regime: str | None
    replayed_production_regime: str | None
    transparent_reference_state: ReferenceMarketState
    input_completeness: Decimal
    timestamp_alignment: TimestampAlignment
    agreement: ClassifierReplayAgreement
    classifier_version: str | None


@dataclass(frozen=True, slots=True)
class MarketStateCounterfactual:
    name: str
    sample_count: int
    regime_distribution: tuple[tuple[str, int], ...]
    score_auc: Decimal | None
    spearman_correlation: Decimal | None
    top_decile_win_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    average_forward_return: Decimal | None
    average_benchmark_relative_return: Decimal | None
    notes: str


@dataclass(frozen=True, slots=True)
class MarketStatePersistenceDecision:
    primary_conclusion: MarketStateConclusion
    secondary_conclusions: tuple[MarketStateConclusion, ...]
    recommended_next_milestone: NextMarketStateMilestone
    prohibited_next_action: str
    explanation: str


@dataclass(frozen=True, slots=True)
class MarketStatePersistenceAuditReport:
    candidate_count: int
    market_dates_covered: int
    authoritative_snapshots_available: int
    fully_reconstructed_snapshots: int
    partially_reconstructed_snapshots: int
    unavailable_snapshots: int
    inventory: tuple[PersistenceInventoryItem, ...]
    snapshots: tuple[HistoricalMarketStateSnapshot, ...]
    timestamp_findings: tuple[TimestampIntegrityFinding, ...]
    timestamp_summary: tuple[TimestampAlignmentSummary, ...]
    fallback_attributions: tuple[FallbackAttribution, ...]
    fallback_summary: tuple[FallbackAttributionSummary, ...]
    state_comparison: StateComparisonSummary
    episodes: tuple[MarketStateEpisode, ...]
    selection_effect: tuple[CandidateSelectionDistribution, ...]
    classifier_replay: tuple[ClassifierReplayResult, ...]
    counterfactuals: tuple[MarketStateCounterfactual, ...]
    decision: MarketStatePersistenceDecision
    recommendation_scores_unchanged: bool
    verdicts_unchanged: bool
    timing_states_unchanged: bool
    approvals_unchanged: bool
    trade_plans_unchanged: bool
    allocations_unchanged: bool
    production_regime_labels_unchanged: bool
    persisted_candidate_records_unchanged: bool


@dataclass(frozen=True, slots=True)
class _AuditRow:
    record: CandidateDecisionRecord
    outcome: CandidateForwardWindowOutcome | None
    entry_state: EntryTimingState
    snapshot: HistoricalMarketStateSnapshot
    timestamp: TimestampIntegrityFinding
    fallback: FallbackAttribution | None
    replay: ClassifierReplayResult
    forward_return: Decimal | None
    benchmark_relative_return: Decimal | None
    profitable: bool | None


class MarketStatePersistenceAuditEngine:
    def __init__(
        self,
        config: MarketStatePersistenceAuditConfig | None = None,
    ) -> None:
        self._config = config or MarketStatePersistenceAuditConfig()

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
        authoritative_snapshots: tuple[MarketStateSnapshot, ...] = (),
    ) -> MarketStatePersistenceAuditReport:
        score_snapshot = {
            record.candidate_id: record.strategy_score for record in records
        }
        verdict_snapshot = {
            record.candidate_id: record.final_verdict for record in records
        }
        plan_snapshot = {
            record.candidate_id: (
                record.entry_zone_low,
                record.entry_zone_high,
                record.confirmation_entry,
                record.risk_stop,
                record.target_1,
                record.target_2,
                record.target_3,
            )
            for record in records
        }
        allocation_snapshot = {
            record.candidate_id: (record.capital_action, record.approved_for_deployment)
            for record in records
        }
        regime_snapshot = {
            record.candidate_id: record.market_regime for record in records
        }
        timing_states = _entry_states(records=records, outcomes=outcomes)
        outcomes_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        snapshots_by_id = {
            snapshot.snapshot_id: snapshot for snapshot in authoritative_snapshots
        }
        rows = tuple(
            self._row(
                record=record,
                outcome=_primary_window(outcomes_by_id.get(record.candidate_id)),
                entry_state=timing_states.get(
                    record.candidate_id,
                    EntryTimingState.ENTRY_UNAVAILABLE,
                ),
                authoritative_snapshot=snapshots_by_id.get(
                    record.market_state_snapshot_id or ""
                ),
            )
            for record in records
        )
        snapshots = tuple(row.snapshot for row in rows)
        findings = tuple(row.timestamp for row in rows)
        fallbacks = tuple(row.fallback for row in rows if row.fallback is not None)
        replay = tuple(row.replay for row in rows)
        decision = _decision(
            rows=rows,
            snapshots=snapshots,
            timestamp_summary=_timestamp_summary(findings),
            fallbacks=fallbacks,
            comparison=_state_comparison(rows),
            minimum_sample=self._config.minimum_sample,
        )
        return MarketStatePersistenceAuditReport(
            candidate_count=len(records),
            market_dates_covered=len({record.evaluation_date for record in records}),
            authoritative_snapshots_available=len(authoritative_snapshots),
            fully_reconstructed_snapshots=sum(
                1
                for item in snapshots
                if item.reconstruction_status
                is MarketStateReconstructionStatus.FULLY_RECONSTRUCTED
            ),
            partially_reconstructed_snapshots=sum(
                1
                for item in snapshots
                if item.reconstruction_status
                is MarketStateReconstructionStatus.PARTIALLY_RECONSTRUCTED
            ),
            unavailable_snapshots=sum(
                1
                for item in snapshots
                if item.reconstruction_status
                in {
                    MarketStateReconstructionStatus.BENCHMARK_UNAVAILABLE,
                    MarketStateReconstructionStatus.RECONSTRUCTION_UNAVAILABLE,
                    MarketStateReconstructionStatus.TIMESTAMP_UNAVAILABLE,
                }
            ),
            inventory=_inventory(
                records,
                authoritative_snapshots=authoritative_snapshots,
            ),
            snapshots=snapshots,
            timestamp_findings=findings,
            timestamp_summary=_timestamp_summary(findings),
            fallback_attributions=fallbacks,
            fallback_summary=_fallback_summary(fallbacks),
            state_comparison=_state_comparison(rows),
            episodes=_episodes(rows),
            selection_effect=_selection_effect(rows),
            classifier_replay=replay,
            counterfactuals=_counterfactuals(rows),
            decision=decision,
            recommendation_scores_unchanged=score_snapshot
            == {record.candidate_id: record.strategy_score for record in records},
            verdicts_unchanged=verdict_snapshot
            == {record.candidate_id: record.final_verdict for record in records},
            timing_states_unchanged=timing_states
            == _entry_states(records=records, outcomes=outcomes),
            approvals_unchanged=allocation_snapshot
            == {
                record.candidate_id: (
                    record.capital_action,
                    record.approved_for_deployment,
                )
                for record in records
            },
            trade_plans_unchanged=plan_snapshot
            == {
                record.candidate_id: (
                    record.entry_zone_low,
                    record.entry_zone_high,
                    record.confirmation_entry,
                    record.risk_stop,
                    record.target_1,
                    record.target_2,
                    record.target_3,
                )
                for record in records
            },
            allocations_unchanged=allocation_snapshot
            == {
                record.candidate_id: (
                    record.capital_action,
                    record.approved_for_deployment,
                )
                for record in records
            },
            production_regime_labels_unchanged=regime_snapshot
            == {record.candidate_id: record.market_regime for record in records},
            persisted_candidate_records_unchanged=True,
        )

    def _row(
        self,
        *,
        record: CandidateDecisionRecord,
        outcome: CandidateForwardWindowOutcome | None,
        entry_state: EntryTimingState,
        authoritative_snapshot: MarketStateSnapshot | None = None,
    ) -> _AuditRow:
        snapshot = _snapshot(record, authoritative_snapshot=authoritative_snapshot)
        timestamp = _timestamp_finding(
            record=record,
            snapshot=snapshot,
            outcome=outcome,
            entry_state=entry_state,
            stale_days=self._config.stale_days,
        )
        fallback = _fallback(record, snapshot, outcome, entry_state)
        replay = _classifier_replay(record, snapshot, timestamp)
        forward_return = (
            None if outcome is None else outcome.forward_return_pct_from_entry
        )
        benchmark = snapshot.benchmark_return_20d or snapshot.benchmark_return_5d
        relative = (
            None
            if forward_return is None or benchmark is None
            else (forward_return - benchmark).quantize(_FOUR)
        )
        return _AuditRow(
            record=record,
            outcome=outcome,
            entry_state=entry_state,
            snapshot=snapshot,
            timestamp=timestamp,
            fallback=fallback,
            replay=replay,
            forward_return=forward_return,
            benchmark_relative_return=relative,
            profitable=None if forward_return is None else forward_return > _ZERO,
        )


def render_market_state_persistence_audit(
    report: MarketStatePersistenceAuditReport,
) -> tuple[str, ...]:
    return (
        "Market State Persistence & Reconstruction Audit",
        f"Total Candidate Records: {report.candidate_count}",
        f"Market Dates Covered: {report.market_dates_covered}",
        (
            "Authoritative Snapshots Available: "
            f"{report.authoritative_snapshots_available}"
        ),
        f"Fully Reconstructed Snapshots: {report.fully_reconstructed_snapshots}",
        (
            "Partially Reconstructed Snapshots: "
            f"{report.partially_reconstructed_snapshots}"
        ),
        f"Unavailable Snapshots: {report.unavailable_snapshots}",
        "",
        "Persistence Inventory:",
        *_inventory_lines(report.inventory),
        "",
        "Timestamp Integrity:",
        *_timestamp_summary_lines(report.timestamp_summary),
        "",
        "Fallback Attribution:",
        *_fallback_lines(report.fallback_summary),
        "",
        "Authoritative vs Reconstructed Comparison:",
        *_comparison_lines(report.state_comparison),
        "",
        "Market Episodes:",
        *_episode_lines(report.episodes),
        "",
        "Candidate Selection Effect:",
        *_selection_lines(report.selection_effect),
        "",
        "Production Classifier Replay:",
        *_classifier_replay_lines(report.classifier_replay),
        "",
        "Diagnostic Counterfactuals:",
        *_counterfactual_lines(report.counterfactuals),
        "",
        f"Primary Conclusion: {report.decision.primary_conclusion.value}",
        "Secondary Conclusion:",
        *(
            [f"- {item.value}" for item in report.decision.secondary_conclusions]
            or ["- none"]
        ),
        (
            "Recommended Next Milestone: "
            f"{report.decision.recommended_next_milestone.value}"
        ),
        f"Explicitly Prohibited Next Action: {report.decision.prohibited_next_action}",
        f"Explanation: {report.decision.explanation}",
        (
            "Policy Integrity: no recommendation scores, verdicts, timing states, "
            "approvals, trade plans, allocations, production regime labels, or "
            "candidate records were changed."
        ),
    )


def group_market_state_persistence_audit(
    report: MarketStatePersistenceAuditReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized in {"status", "reconstruction"}:
        return (
            "Market State Reconstruction:",
            *_snapshot_status_lines(report.snapshots),
        )
    if normalized == "fallback":
        return ("Market State Fallbacks:", *_fallback_lines(report.fallback_summary))
    if normalized in {"inventory", "persistence"}:
        return ("Market State Inventory:", *_inventory_lines(report.inventory))
    if normalized in {"timestamp", "timestamps"}:
        return (
            "Market State Timestamps:",
            *_timestamp_summary_lines(report.timestamp_summary),
        )
    if normalized == "comparison":
        return ("Market State Comparison:", *_comparison_lines(report.state_comparison))
    if normalized == "episodes":
        return ("Market State Episodes:", *_episode_lines(report.episodes))
    if normalized in {"selection", "selection-effect"}:
        return (
            "Candidate Selection Effect:",
            *_selection_lines(report.selection_effect),
        )
    if normalized in {"classifier", "classifier-replay"}:
        return (
            "Market State Classifier Replay:",
            *_classifier_replay_lines(report.classifier_replay),
        )
    if normalized == "counterfactuals":
        return (
            "Market State Counterfactuals:",
            *_counterfactual_lines(report.counterfactuals),
        )
    return render_market_state_persistence_audit(report)


def export_market_state_persistence_audit_json(
    report: MarketStatePersistenceAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report_dict(report), indent=2, default=str), encoding="utf-8"
    )
    return path


def export_market_state_persistence_audit_csv(
    report: MarketStatePersistenceAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = tuple(_snapshot_dict(item) for item in report.snapshots)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=tuple(rows[0]) if rows else ("as_of",)
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _entry_states(
    *,
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> dict[str, EntryTimingState]:
    return {
        row.candidate_id: row.assessment.entry_state
        for row in build_entry_timing_replay_report(
            records=records,
            outcomes=outcomes,
        ).rows
    }


def _snapshot(
    record: CandidateDecisionRecord,
    *,
    authoritative_snapshot: MarketStateSnapshot | None = None,
) -> HistoricalMarketStateSnapshot:
    if authoritative_snapshot is not None:
        return _authoritative_snapshot(record, authoritative_snapshot)
    used: list[str] = []
    missing: list[str] = []
    benchmark_return_1d = _indicator(record, ("benchmark-return-1d",))
    benchmark_return_5d = _indicator(record, ("benchmark-return-5d",))
    benchmark_return_20d = _indicator(
        record,
        ("benchmark-return-20d", "benchmark-return", "benchmark_return"),
    )
    benchmark_close = _indicator(record, ("benchmark-close",))
    trend = _indicator(record, ("market-trend-score", "trend", "price"))
    breadth = _indicator(record, ("breadth-score", "breadth-ratio"))
    volatility = _indicator(record, ("volatility-score", "atr", "benchmark-atr"))
    participation = _indicator(record, ("participation-score", "volume"))
    percent_20 = _indicator(record, ("percent-above-20dma",))
    percent_50 = _indicator(record, ("percent-above-50dma",))
    percent_200 = _indicator(record, ("percent-above-200dma",))
    fields = {
        "benchmark_return_20d": benchmark_return_20d,
        "market_trend_score": trend,
        "breadth_score": breadth,
        "volatility_score": volatility,
        "participation_score": participation,
    }
    for field, value in fields.items():
        if value is None:
            missing.append(field)
        else:
            used.append(field)
    status = _reconstruction_status(used=tuple(used), missing=tuple(missing))
    completeness = _rate(len(used), len(used) + len(missing)) or _ZERO
    return HistoricalMarketStateSnapshot(
        as_of=record.created_at.isoformat(),
        market_date=record.evaluation_date.isoformat(),
        source_timestamp=_source_timestamp(record),
        benchmark_symbol=_text_indicator(record, ("benchmark-symbol",)),
        benchmark_close=benchmark_close,
        benchmark_return_1d=benchmark_return_1d,
        benchmark_return_5d=benchmark_return_5d,
        benchmark_return_20d=benchmark_return_20d,
        benchmark_above_20dma=_bool_indicator(record, ("benchmark-above-20dma",)),
        benchmark_above_50dma=_bool_indicator(record, ("benchmark-above-50dma",)),
        benchmark_above_200dma=_bool_indicator(record, ("benchmark-above-200dma",)),
        benchmark_distance_20dma=_indicator(record, ("benchmark-distance-20dma",)),
        benchmark_distance_50dma=_indicator(record, ("benchmark-distance-50dma",)),
        benchmark_distance_200dma=_indicator(record, ("benchmark-distance-200dma",)),
        benchmark_atr=_indicator(record, ("benchmark-atr",)),
        benchmark_volatility=volatility,
        breadth_advancers=_int_indicator(record, ("breadth-advancers",)),
        breadth_decliners=_int_indicator(record, ("breadth-decliners",)),
        breadth_unchanged=_int_indicator(record, ("breadth-unchanged",)),
        breadth_ratio=breadth,
        percent_above_20dma=percent_20,
        percent_above_50dma=percent_50,
        percent_above_200dma=percent_200,
        new_highs=_int_indicator(record, ("new-highs",)),
        new_lows=_int_indicator(record, ("new-lows",)),
        sector_leadership=record.sector,
        sector_dispersion=_indicator(record, ("sector-dispersion",)),
        market_trend_score=trend,
        breadth_score=breadth,
        volatility_score=volatility,
        participation_score=participation,
        reference_state=_reference_state(
            benchmark_return=benchmark_return_20d,
            trend=trend,
            volatility=volatility,
        ),
        production_regime=record.market_regime,
        production_regime_confidence=_indicator(
            record,
            ("production-regime-confidence", "market-regime"),
        ),
        classifier_version=_text_indicator(record, ("classifier-version",)),
        source_completeness=completeness,
        reconstruction_status=status,
        missing_fields=tuple(missing),
        source_fields_used=tuple(used),
        lookback_bars_available=int(
            _indicator(record, ("lookback-bars-available",)) or Decimal("0")
        ),
        universe_size=_int_indicator(record, ("universe-size",)),
        benchmark_available=benchmark_return_20d is not None
        or benchmark_close is not None,
        breadth_available=breadth is not None,
        sector_data_available=record.sector is not None,
        confidence_or_completeness_grade=_grade(completeness),
    )


def _authoritative_snapshot(
    record: CandidateDecisionRecord,
    snapshot: MarketStateSnapshot,
) -> HistoricalMarketStateSnapshot:
    missing = snapshot.missing_fields
    used = tuple(
        field
        for field, value in (
            ("benchmark_close", snapshot.benchmark_close),
            ("benchmark_return_1d", snapshot.benchmark_return_1d),
            ("benchmark_return_5d", snapshot.benchmark_return_5d),
            ("benchmark_return_20d", snapshot.benchmark_return_20d),
            ("market_trend_score", snapshot.market_trend_score),
            ("breadth_score", snapshot.breadth_score),
            ("volatility_score", snapshot.volatility_score),
            ("participation_score", snapshot.participation_score),
        )
        if value is not None
    )
    return HistoricalMarketStateSnapshot(
        as_of=snapshot.as_of_timestamp.isoformat(),
        market_date=snapshot.market_date.isoformat(),
        source_timestamp=snapshot.source_timestamp.isoformat(),
        benchmark_symbol=snapshot.benchmark_symbol,
        benchmark_close=snapshot.benchmark_close,
        benchmark_return_1d=snapshot.benchmark_return_1d,
        benchmark_return_5d=snapshot.benchmark_return_5d,
        benchmark_return_20d=snapshot.benchmark_return_20d,
        benchmark_above_20dma=snapshot.benchmark_above_20dma,
        benchmark_above_50dma=snapshot.benchmark_above_50dma,
        benchmark_above_200dma=snapshot.benchmark_above_200dma,
        benchmark_distance_20dma=snapshot.benchmark_distance_20dma,
        benchmark_distance_50dma=snapshot.benchmark_distance_50dma,
        benchmark_distance_200dma=snapshot.benchmark_distance_200dma,
        benchmark_atr=snapshot.benchmark_atr,
        benchmark_volatility=snapshot.benchmark_volatility,
        breadth_advancers=snapshot.breadth_advancers,
        breadth_decliners=snapshot.breadth_decliners,
        breadth_unchanged=snapshot.breadth_unchanged,
        breadth_ratio=snapshot.breadth_ratio,
        percent_above_20dma=snapshot.percent_above_20dma,
        percent_above_50dma=snapshot.percent_above_50dma,
        percent_above_200dma=snapshot.percent_above_200dma,
        new_highs=snapshot.new_highs,
        new_lows=snapshot.new_lows,
        sector_leadership=snapshot.sector_leader or record.sector,
        sector_dispersion=snapshot.sector_dispersion,
        market_trend_score=snapshot.market_trend_score,
        breadth_score=snapshot.breadth_score,
        volatility_score=snapshot.volatility_score,
        participation_score=snapshot.participation_score,
        reference_state=_reference_state(
            benchmark_return=snapshot.benchmark_return_20d,
            trend=snapshot.market_trend_score,
            volatility=snapshot.volatility_score,
        ),
        production_regime=snapshot.classifier_regime,
        production_regime_confidence=snapshot.classifier_confidence,
        classifier_version=snapshot.classifier_version,
        source_completeness=_completeness_value(snapshot.input_completeness.value),
        reconstruction_status=MarketStateReconstructionStatus.AUTHORITATIVE,
        missing_fields=missing,
        source_fields_used=used,
        lookback_bars_available=0,
        universe_size=None,
        benchmark_available=snapshot.benchmark_close is not None
        or snapshot.benchmark_return_20d is not None,
        breadth_available=snapshot.breadth_ratio is not None,
        sector_data_available=snapshot.sector_leader is not None,
        confidence_or_completeness_grade=snapshot.input_completeness.value,
    )


def _reconstruction_status(
    *,
    used: tuple[str, ...],
    missing: tuple[str, ...],
) -> MarketStateReconstructionStatus:
    if not used:
        return MarketStateReconstructionStatus.RECONSTRUCTION_UNAVAILABLE
    if not missing:
        return MarketStateReconstructionStatus.FULLY_RECONSTRUCTED
    if "benchmark_return_20d" in missing:
        return MarketStateReconstructionStatus.PARTIALLY_RECONSTRUCTED
    return MarketStateReconstructionStatus.PARTIALLY_RECONSTRUCTED


def _completeness_value(value: str) -> Decimal:
    scores = {
        "COMPLETE": Decimal("1.0000"),
        "PARTIAL": Decimal("0.7500"),
        "MINIMUM_VIABLE": Decimal("0.5000"),
        "INSUFFICIENT": Decimal("0.2500"),
        "UNAVAILABLE": Decimal("0.0000"),
    }
    return scores.get(value, Decimal("0.0000"))


def _timestamp_finding(
    *,
    record: CandidateDecisionRecord,
    snapshot: HistoricalMarketStateSnapshot,
    outcome: CandidateForwardWindowOutcome | None,
    entry_state: EntryTimingState,
    stale_days: int,
) -> TimestampIntegrityFinding:
    source_date = _source_date(record)
    if snapshot.reconstruction_status is MarketStateReconstructionStatus.AUTHORITATIVE:
        snapshot_date = (
            None
            if snapshot.market_date is None
            else date.fromisoformat(snapshot.market_date)
        )
        if snapshot_date is None:
            alignment = TimestampAlignment.SNAPSHOT_RECORD_MISSING
            issue = "Linked authoritative market-state snapshot has no market date."
            staleness = None
        else:
            staleness = (record.evaluation_date - snapshot_date).days
            if snapshot_date > record.evaluation_date:
                alignment = TimestampAlignment.AUTHORITATIVE_SNAPSHOT_FUTURE_INVALID
                issue = (
                    "Authoritative market-state snapshot is after the candidate "
                    "decision date."
                )
            elif snapshot.source_timestamp == record.created_at.isoformat():
                alignment = TimestampAlignment.AUTHORITATIVE_SNAPSHOT_EXACT
                issue = (
                    "Authoritative market-state source timestamp matches decision "
                    "timestamp."
                )
            elif staleness == 0:
                alignment = TimestampAlignment.AUTHORITATIVE_SNAPSHOT_SAME_DAY
                issue = (
                    "Authoritative market-state snapshot matches candidate market date."
                )
            elif staleness <= stale_days:
                alignment = TimestampAlignment.CARRIED_FORWARD_VALID
                issue = (
                    "Authoritative market state was carried forward within tolerance."
                )
            else:
                alignment = TimestampAlignment.AUTHORITATIVE_SNAPSHOT_STALE
                issue = (
                    "Authoritative market state was carried forward beyond tolerance."
                )
    elif record.market_state_snapshot_id is not None:
        alignment = TimestampAlignment.SNAPSHOT_RECORD_MISSING
        issue = "Candidate references a market-state snapshot that is not available."
        staleness = None
    elif snapshot.source_timestamp is None and record.market_regime is None:
        alignment = TimestampAlignment.MISSING_TIMESTAMP
        issue = "No market-state source timestamp or candidate regime exists."
        staleness = None
    elif source_date is None and _is_default_neutral(record, snapshot):
        alignment = TimestampAlignment.DEFAULTED_WITHOUT_SOURCE
        issue = "Candidate is neutral/defaulted without a persisted source timestamp."
        staleness = None
    elif source_date is None:
        alignment = TimestampAlignment.RECONSTRUCTED_SAME_DATE
        issue = "No source timestamp; diagnostic uses same-date candidate fields."
        staleness = 0
    else:
        staleness = (record.evaluation_date - source_date).days
        if source_date > record.evaluation_date:
            alignment = TimestampAlignment.FUTURE_TIMESTAMP
            issue = "Market-state source timestamp is after the decision date."
        elif staleness == 0:
            alignment = TimestampAlignment.EXACT
            issue = "Market-state timestamp matches candidate date."
        elif staleness <= stale_days:
            alignment = TimestampAlignment.CARRIED_FORWARD_VALID
            issue = "Market state was carried forward within tolerance."
        else:
            alignment = TimestampAlignment.CARRIED_FORWARD_STALE
            issue = "Market state was carried forward beyond tolerance."
    return TimestampIntegrityFinding(
        candidate_id=record.candidate_id,
        symbol=record.symbol,
        candidate_decision_timestamp=record.created_at.isoformat(),
        market_state_source_timestamp=snapshot.source_timestamp,
        classifier_timestamp=snapshot.source_timestamp,
        attached_regime_timestamp=snapshot.market_date,
        recommendation_timestamp=record.created_at.isoformat(),
        replay_timestamp=record.evaluation_date.isoformat(),
        alignment=alignment,
        staleness_days=staleness,
        completed_outcome=outcome is not None,
        buy_candidate=record.final_verdict in _POSITIVE_VERDICTS,
        acceptably_timed=entry_state in _PRIMARY_ENTRY_STATES,
        issue=issue,
    )


def _fallback(
    record: CandidateDecisionRecord,
    snapshot: HistoricalMarketStateSnapshot,
    outcome: CandidateForwardWindowOutcome | None,
    entry_state: EntryTimingState,
) -> FallbackAttribution | None:
    if (record.market_regime or "").strip().upper() != "NEUTRAL":
        return None
    reasons: list[NeutralFallbackReason] = []
    if not snapshot.benchmark_available:
        reasons.append(NeutralFallbackReason.MISSING_BENCHMARK_INPUT)
    if not snapshot.breadth_available:
        reasons.append(NeutralFallbackReason.MISSING_BREADTH_INPUT)
    if snapshot.volatility_score is None:
        reasons.append(NeutralFallbackReason.MISSING_VOLATILITY_INPUT)
    if not snapshot.sector_data_available:
        reasons.append(NeutralFallbackReason.MISSING_SECTOR_INPUT)
    if snapshot.lookback_bars_available and snapshot.lookback_bars_available < 50:
        reasons.append(NeutralFallbackReason.INSUFFICIENT_LOOKBACK)
    if _has_missing_text(record):
        reasons.append(NeutralFallbackReason.MISSING_MARKET_STATE_RECORD)
    if not reasons:
        reasons.append(NeutralFallbackReason.GENUINE_NEUTRAL_CLASSIFICATION)
    forward = None if outcome is None else outcome.forward_return_pct_from_entry
    benchmark = snapshot.benchmark_return_20d or snapshot.benchmark_return_5d
    relative = None if forward is None or benchmark is None else forward - benchmark
    return FallbackAttribution(
        candidate_id=record.candidate_id,
        symbol=record.symbol,
        market_date=record.evaluation_date.isoformat(),
        setup_type=record.setup_type,
        verdict=record.final_verdict,
        entry_state=entry_state,
        reference_state=snapshot.reference_state,
        primary_reason=reasons[0],
        secondary_reasons=tuple(dict.fromkeys(reasons[1:])),
        completed_outcome=outcome is not None,
        profitable=None if forward is None else forward > _ZERO,
        benchmark_relative_outcome=None
        if relative is None
        else relative.quantize(_FOUR),
    )


def _classifier_replay(
    record: CandidateDecisionRecord,
    snapshot: HistoricalMarketStateSnapshot,
    timestamp: TimestampIntegrityFinding,
) -> ClassifierReplayResult:
    replayed = _diagnostic_replayed_regime(snapshot)
    original = _canonical_regime(record.market_regime)
    if replayed is None:
        agreement = ClassifierReplayAgreement.REPLAY_UNAVAILABLE
        replayed_text = None
    else:
        replayed_text = replayed.value
        if original.value == replayed.value:
            agreement = ClassifierReplayAgreement.EXACT_MATCH
        elif _same_direction(original, replayed):
            agreement = ClassifierReplayAgreement.DIRECTIONAL_MATCH
        elif original is CanonicalRegime.NEUTRAL and replayed not in {
            CanonicalRegime.NEUTRAL,
            CanonicalRegime.SIDEWAYS,
        }:
            agreement = ClassifierReplayAgreement.NEUTRAL_COLLAPSE
        elif original is CanonicalRegime.UNAVAILABLE:
            agreement = ClassifierReplayAgreement.ORIGINAL_DEFAULTED
        else:
            agreement = ClassifierReplayAgreement.SIGN_CONFLICT
    return ClassifierReplayResult(
        candidate_id=record.candidate_id,
        symbol=record.symbol,
        original_attached_regime=record.market_regime,
        replayed_production_regime=replayed_text,
        transparent_reference_state=snapshot.reference_state,
        input_completeness=snapshot.source_completeness,
        timestamp_alignment=timestamp.alignment,
        agreement=agreement,
        classifier_version=snapshot.classifier_version,
    )


def _inventory(
    records: tuple[CandidateDecisionRecord, ...],
    *,
    authoritative_snapshots: tuple[MarketStateSnapshot, ...] = (),
) -> tuple[PersistenceInventoryItem, ...]:
    dates = tuple(record.evaluation_date for record in records)
    snapshot_dates = tuple(snapshot.market_date for snapshot in authoritative_snapshots)
    return (
        _inventory_item(
            "CandidateDecisionRecord.market_regime",
            records,
            coverage=sum(1 for record in records if record.market_regime is not None),
            status=MarketStateFeatureStatus.PERSISTED_PARTIAL,
            notes=(
                "Candidate-linked regime label exists, but source snapshot is absent."
            ),
        ),
        _inventory_item(
            "CandidateDecisionRecord.created_at",
            records,
            coverage=len(records),
            status=MarketStateFeatureStatus.PERSISTED_PARTIAL,
            notes=(
                "Recommendation timestamp exists; market-state source timestamp "
                "does not."
            ),
        ),
        _inventory_item(
            "indicator_scores.price/trend/volume",
            records,
            coverage=sum(
                1
                for record in records
                if _indicator(record, ("price", "trend", "volume")) is not None
            ),
            status=MarketStateFeatureStatus.RECONSTRUCTABLE_WITH_LIMITATIONS,
            notes=(
                "Same-date candidate components can support diagnostic reconstruction."
            ),
        ),
        _inventory_item(
            "benchmark history",
            records,
            coverage=sum(
                1
                for record in records
                if _indicator(record, ("benchmark-return", "benchmark-return-20d"))
                is not None
            ),
            status=MarketStateFeatureStatus.RECONSTRUCTABLE_WITH_LIMITATIONS,
            notes="Only available when recorded in candidate indicator scores.",
        ),
        PersistenceInventoryItem(
            field="authoritative market-state snapshot",
            source_model="MarketStateSnapshot",
            source_table_file=".alpha/market_state_snapshots.json",
            persisted_or_transient=(
                "persisted" if authoritative_snapshots else "not persisted"
            ),
            timestamped_or_untimestamped=(
                "timestamped" if authoritative_snapshots else "missing"
            ),
            candidate_linked_or_market_level="market-level expected",
            authoritative_or_reconstructed=(
                MarketStateFeatureStatus.PERSISTED_AUTHORITATIVE
                if authoritative_snapshots
                else MarketStateFeatureStatus.NOT_AVAILABLE
            ),
            coverage_count=len(authoritative_snapshots),
            first_date=(
                min(snapshot_dates).isoformat()
                if snapshot_dates
                else (min(dates).isoformat() if dates else None)
            ),
            last_date=(
                max(snapshot_dates).isoformat()
                if snapshot_dates
                else (max(dates).isoformat() if dates else None)
            ),
            missing_rate=(
                None
                if not records
                else _rate(
                    len({record.evaluation_date for record in records})
                    - len(set(snapshot_dates)),
                    len({record.evaluation_date for record in records}),
                )
            ),
            notes=(
                "Authoritative point-in-time market-state snapshots are persisted."
                if authoritative_snapshots
                else "No authoritative historical market-state snapshots are present."
            ),
        ),
        _inventory_item(
            "CandidateDecisionRecord.market_state_snapshot_id",
            records,
            coverage=sum(
                1 for record in records if record.market_state_snapshot_id is not None
            ),
            status=(
                MarketStateFeatureStatus.PERSISTED_AUTHORITATIVE
                if authoritative_snapshots
                else MarketStateFeatureStatus.NOT_AVAILABLE
            ),
            notes="Candidate-to-market-state snapshot linkage for newly recorded runs.",
        ),
    )


def _inventory_item(
    field: str,
    records: tuple[CandidateDecisionRecord, ...],
    *,
    coverage: int,
    status: MarketStateFeatureStatus,
    notes: str,
) -> PersistenceInventoryItem:
    dates = tuple(record.evaluation_date for record in records)
    return PersistenceInventoryItem(
        field=field,
        source_model="CandidateDecisionRecord",
        source_table_file="candidate_learning_ledger.json",
        persisted_or_transient="persisted",
        timestamped_or_untimestamped="timestamped" if records else "unavailable",
        candidate_linked_or_market_level="candidate-linked",
        authoritative_or_reconstructed=status,
        coverage_count=coverage,
        first_date=min(dates).isoformat() if dates else None,
        last_date=max(dates).isoformat() if dates else None,
        missing_rate=_rate(len(records) - coverage, len(records)),
        notes=notes,
    )


def _timestamp_summary(
    findings: tuple[TimestampIntegrityFinding, ...],
) -> tuple[TimestampAlignmentSummary, ...]:
    grouped: dict[TimestampAlignment, list[TimestampIntegrityFinding]] = defaultdict(
        list
    )
    for finding in findings:
        grouped[finding.alignment].append(finding)
    result = []
    for alignment, items in sorted(grouped.items(), key=lambda item: item[0].value):
        rows = tuple(items)
        stale_values = tuple(
            Decimal(item.staleness_days)
            for item in rows
            if item.staleness_days is not None
        )
        result.append(
            TimestampAlignmentSummary(
                alignment=alignment,
                count=len(rows),
                percentage=_rate(len(rows), len(findings)),
                oldest_example=min(item.candidate_id for item in rows),
                newest_example=max(item.candidate_id for item in rows),
                maximum_staleness_days=max(
                    (
                        item.staleness_days
                        for item in rows
                        if item.staleness_days is not None
                    ),
                    default=None,
                ),
                median_staleness_days=_median(stale_values),
                completed_outcomes_affected=sum(
                    1 for item in rows if item.completed_outcome
                ),
                buy_candidates_affected=sum(1 for item in rows if item.buy_candidate),
                acceptably_timed_candidates_affected=sum(
                    1 for item in rows if item.acceptably_timed
                ),
            )
        )
    return tuple(result)


def _fallback_summary(
    fallbacks: tuple[FallbackAttribution, ...],
) -> tuple[FallbackAttributionSummary, ...]:
    grouped: dict[NeutralFallbackReason, list[FallbackAttribution]] = defaultdict(list)
    for item in fallbacks:
        grouped[item.primary_reason].append(item)
    return tuple(
        FallbackAttributionSummary(
            reason=reason,
            candidate_count=len(items),
            completed_outcomes=sum(1 for item in items if item.completed_outcome),
            win_rate=_rate(
                sum(1 for item in items if item.profitable is True),
                sum(1 for item in items if item.profitable is not None),
            ),
            setup_counts=tuple(
                sorted(Counter(item.setup_type or "UNKNOWN" for item in items).items())
            ),
            verdict_counts=tuple(
                sorted(Counter(item.verdict for item in items).items())
            ),
        )
        for reason, items in sorted(grouped.items(), key=lambda item: item[0].value)
    )


def _state_comparison(rows: tuple[_AuditRow, ...]) -> StateComparisonSummary:
    comparable = tuple(
        row
        for row in rows
        if row.snapshot.reconstruction_status
        is not MarketStateReconstructionStatus.RECONSTRUCTION_UNAVAILABLE
    )
    exact = sum(
        1
        for row in comparable
        if _canonical_regime(row.record.market_regime)
        == _diagnostic_replayed_regime(row.snapshot)
    )
    directional = sum(
        1
        for row in comparable
        if _same_direction(
            _canonical_regime(row.record.market_regime),
            _diagnostic_replayed_regime(row.snapshot),
        )
    )
    extreme = tuple(
        row
        for row in comparable
        if row.snapshot.reference_state
        in {
            ReferenceMarketState.BEARISH_TREND,
            ReferenceMarketState.BULLISH_TREND,
            ReferenceMarketState.CORRECTION,
            ReferenceMarketState.HIGH_VOLATILITY,
        }
    )
    collapse = sum(
        1
        for row in extreme
        if _canonical_regime(row.record.market_regime) is CanonicalRegime.NEUTRAL
    )
    return StateComparisonSummary(
        sample_count=len(comparable),
        exact_regime_agreement=_rate(exact, len(comparable)),
        directional_agreement=_rate(directional, len(comparable)),
        neutral_disagreement_rate=_rate(
            sum(
                1
                for row in comparable
                if _canonical_regime(row.record.market_regime)
                is CanonicalRegime.NEUTRAL
                and _diagnostic_replayed_regime(row.snapshot)
                not in {CanonicalRegime.NEUTRAL, CanonicalRegime.SIDEWAYS, None}
            ),
            len(comparable),
        ),
        extreme_to_neutral_collapse_rate=_rate(collapse, len(extreme)),
        balanced_accuracy=_rate(directional, len(comparable)),
        timestamp_difference_days=Decimal("0") if comparable else None,
        notes="Reconstructed state is a diagnostic comparator, not ground truth.",
    )


def _episodes(rows: tuple[_AuditRow, ...]) -> tuple[MarketStateEpisode, ...]:
    grouped: dict[MarketEpisodeType, list[_AuditRow]] = defaultdict(list)
    for row in rows:
        grouped[_episode_type(row.snapshot)].append(row)
    result = []
    for episode_type, items in sorted(grouped.items(), key=lambda item: item[0].value):
        group = tuple(items)
        dates = tuple(row.record.evaluation_date for row in group)
        returns = tuple(row.forward_return for row in group)
        fallbacks = Counter(
            row.fallback.primary_reason.value
            for row in group
            if row.fallback is not None
        )
        result.append(
            MarketStateEpisode(
                episode_type=episode_type,
                start=min(dates).isoformat(),
                end=max(dates).isoformat(),
                trading_days=len(set(dates)),
                candidate_count=len(group),
                buy_count=sum(
                    1 for row in group if row.record.final_verdict in _POSITIVE_VERDICTS
                ),
                acceptable_entry_count=sum(
                    1 for row in group if row.entry_state in _PRIMARY_ENTRY_STATES
                ),
                win_rate=_rate(
                    sum(1 for row in group if row.profitable is True),
                    sum(1 for row in group if row.profitable is not None),
                ),
                average_return=_average(returns),
                median_return=_median(
                    tuple(value for value in returns if value is not None)
                ),
                maximum_adverse_excursion=_average(
                    tuple(
                        None
                        if row.outcome is None
                        else row.outcome.max_adverse_excursion_pct
                        for row in group
                    )
                ),
                maximum_favourable_excursion=_average(
                    tuple(
                        None
                        if row.outcome is None
                        else row.outcome.max_favourable_excursion_pct
                        for row in group
                    )
                ),
                production_regime_distribution=tuple(
                    sorted(
                        Counter(
                            _regime_text(row.record.market_regime) for row in group
                        ).items()
                    )
                ),
                fallback_distribution=tuple(sorted(fallbacks.items())),
            )
        )
    return tuple(result)


def _selection_effect(
    rows: tuple[_AuditRow, ...],
) -> tuple[CandidateSelectionDistribution, ...]:
    stages = (
        ("all generated candidates", rows),
        (
            "BUY candidates",
            tuple(
                row for row in rows if row.record.final_verdict in _POSITIVE_VERDICTS
            ),
        ),
        (
            "approved candidates",
            tuple(row for row in rows if row.record.approved_for_deployment),
        ),
        ("completed outcomes", tuple(row for row in rows if row.outcome is not None)),
        (
            "acceptably timed candidates",
            tuple(row for row in rows if row.entry_state in _PRIMARY_ENTRY_STATES),
        ),
    )
    return tuple(
        _selection_distribution(stage, tuple(items)) for stage, items in stages
    )


def _selection_distribution(
    stage: str,
    rows: tuple[_AuditRow, ...],
) -> CandidateSelectionDistribution:
    distribution = Counter(row.snapshot.reference_state.value for row in rows)
    neutral = sum(
        1
        for row in rows
        if _canonical_regime(row.record.market_regime) is CanonicalRegime.NEUTRAL
    )
    bearish = sum(
        1
        for row in rows
        if row.snapshot.reference_state
        in {ReferenceMarketState.BEARISH_TREND, ReferenceMarketState.CORRECTION}
    )
    return CandidateSelectionDistribution(
        stage=stage,
        sample_count=len(rows),
        market_state_distribution=tuple(sorted(distribution.items())),
        neutral_share=_rate(neutral, len(rows)),
        bearish_reference_share=_rate(bearish, len(rows)),
        notes="Associative distribution only; this audit does not infer causality.",
    )


def _counterfactuals(
    rows: tuple[_AuditRow, ...],
) -> tuple[MarketStateCounterfactual, ...]:
    views = (
        (
            "AUTHORITATIVE_STATE_ONLY",
            tuple(
                row
                for row in rows
                if row.snapshot.reconstruction_status
                is MarketStateReconstructionStatus.AUTHORITATIVE
            ),
        ),
        (
            "RECONSTRUCTED_STATE_ONLY",
            tuple(
                row
                for row in rows
                if row.snapshot.reconstruction_status
                in {
                    MarketStateReconstructionStatus.FULLY_RECONSTRUCTED,
                    MarketStateReconstructionStatus.PARTIALLY_RECONSTRUCTED,
                }
            ),
        ),
        (
            "NO_DEFAULT_NEUTRAL",
            tuple(
                row
                for row in rows
                if row.fallback is None
                or row.fallback.primary_reason
                is not NeutralFallbackReason.REGIME_FIELD_DEFAULT_VALUE
            ),
        ),
        (
            "MISSING_STATE_EXCLUDED",
            tuple(
                row
                for row in rows
                if row.snapshot.reconstruction_status
                is not MarketStateReconstructionStatus.RECONSTRUCTION_UNAVAILABLE
            ),
        ),
        (
            "STALE_STATE_EXCLUDED",
            tuple(
                row
                for row in rows
                if row.timestamp.alignment
                is not TimestampAlignment.CARRIED_FORWARD_STALE
            ),
        ),
        (
            "EXACT_TIMESTAMP_ONLY",
            tuple(
                row
                for row in rows
                if row.timestamp.alignment
                in {
                    TimestampAlignment.EXACT,
                    TimestampAlignment.SAME_TRADING_DAY,
                    TimestampAlignment.RECONSTRUCTED_SAME_DATE,
                }
            ),
        ),
        (
            "COMPLETE_INPUTS_ONLY",
            tuple(
                row
                for row in rows
                if row.snapshot.source_completeness >= Decimal("0.80")
            ),
        ),
        ("REFERENCE_STATE_GROUPING", rows),
        (
            "PRODUCTION_CLASSIFIER_REPLAY",
            tuple(
                row
                for row in rows
                if row.replay.agreement
                is not ClassifierReplayAgreement.REPLAY_UNAVAILABLE
            ),
        ),
    )
    return tuple(_counterfactual(name, sample) for name, sample in views)


def _counterfactual(
    name: str,
    rows: tuple[_AuditRow, ...],
) -> MarketStateCounterfactual:
    scores = tuple(row.record.strategy_score for row in rows)
    labels = tuple(row.profitable is True for row in rows)
    returns = tuple(row.forward_return for row in rows)
    return MarketStateCounterfactual(
        name=name,
        sample_count=len(rows),
        regime_distribution=tuple(
            sorted(
                Counter(_regime_text(row.record.market_regime) for row in rows).items()
            )
        ),
        score_auc=_roc_auc(scores, labels),
        spearman_correlation=_spearman(scores, returns),
        top_decile_win_rate=_top_decile_win_rate(rows),
        buy_precision_proxy=_rate(
            sum(
                1
                for row in rows
                if row.record.final_verdict in _POSITIVE_VERDICTS
                and row.profitable is True
            ),
            sum(1 for row in rows if row.record.final_verdict in _POSITIVE_VERDICTS),
        ),
        average_forward_return=_average(returns),
        average_benchmark_relative_return=_average(
            tuple(row.benchmark_relative_return for row in rows)
        ),
        notes="Research-only view; production recommendations are unchanged.",
    )


def _decision(
    *,
    rows: tuple[_AuditRow, ...],
    snapshots: tuple[HistoricalMarketStateSnapshot, ...],
    timestamp_summary: tuple[TimestampAlignmentSummary, ...],
    fallbacks: tuple[FallbackAttribution, ...],
    comparison: StateComparisonSummary,
    minimum_sample: int,
) -> MarketStatePersistenceDecision:
    if len(rows) < minimum_sample:
        primary = (
            MarketStateConclusion.INSUFFICIENT_EVIDENCE_FOR_MARKET_STATE_CONCLUSION
        )
        milestone = NextMarketStateMilestone.INSUFFICIENT_EVIDENCE_COLLECT_MORE_HISTORY
    elif not any(
        item.reconstruction_status is MarketStateReconstructionStatus.AUTHORITATIVE
        for item in snapshots
    ):
        primary = MarketStateConclusion.MARKET_STATE_HISTORY_NOT_PERSISTED
        milestone = NextMarketStateMilestone.ADD_AUTHORITATIVE_MARKET_STATE_SNAPSHOTS
    elif any(
        item.alignment is TimestampAlignment.FUTURE_TIMESTAMP
        for item in timestamp_summary
    ):
        primary = (
            MarketStateConclusion.MARKET_STATE_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK
        )
        milestone = NextMarketStateMilestone.ADD_MARKET_STATE_TIMESTAMP_LINKAGE
    elif authoritative_count := sum(
        1
        for item in snapshots
        if item.reconstruction_status is MarketStateReconstructionStatus.AUTHORITATIVE
    ):
        primary = MarketStateConclusion.DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK
        if authoritative_count < len(rows):
            milestone = NextMarketStateMilestone[
                "AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN"
            ]
        else:
            milestone = NextMarketStateMilestone.HARDEN_MARKET_STATE_CAPTURE
    elif _fallback_rate(fallbacks, rows) >= Decimal("0.70"):
        primary = MarketStateConclusion.DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK
        milestone = NextMarketStateMilestone.HARDEN_MARKET_STATE_CAPTURE
    elif (
        comparison.extreme_to_neutral_collapse_rate is not None
        and comparison.extreme_to_neutral_collapse_rate >= Decimal("0.50")
    ):
        primary = (
            MarketStateConclusion.CANDIDATE_REGIME_ATTACHMENT_IS_PRIMARY_BOTTLENECK
        )
        milestone = NextMarketStateMilestone.REPAIR_CANDIDATE_REGIME_ATTACHMENT
    else:
        primary = MarketStateConclusion.PRODUCTION_CLASSIFIER_APPEARS_CONSISTENT
        milestone = NextMarketStateMilestone.AUDIT_PRODUCTION_REGIME_THRESHOLDS
    secondary = []
    if any(
        item.alignment is TimestampAlignment.FUTURE_TIMESTAMP
        for item in timestamp_summary
    ):
        secondary.append(
            MarketStateConclusion.MARKET_STATE_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK
        )
    if _selection_neutral_concentration(rows) >= Decimal("0.80"):
        secondary.append(
            MarketStateConclusion.CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_BOTTLENECK
        )
    authoritative_count = sum(
        1
        for item in snapshots
        if item.reconstruction_status is MarketStateReconstructionStatus.AUTHORITATIVE
    )
    return MarketStatePersistenceDecision(
        primary_conclusion=primary,
        secondary_conclusions=tuple(dict.fromkeys(secondary)),
        recommended_next_milestone=milestone,
        prohibited_next_action=(
            "Do not change classifier thresholds, labels, scores, gates, "
            "retracement signs, verdicts, approvals, allocation, or historical "
            "candidate records from this diagnostic audit."
        ),
        explanation=(
            f"{primary.value}. Authoritative candidate rows linked: "
            f"{authoritative_count}."
        ),
    )


def _source_timestamp(record: CandidateDecisionRecord) -> str | None:
    value = _text_indicator(record, ("market-state-source-date", "source-timestamp"))
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _source_date(record: CandidateDecisionRecord) -> date | None:
    value = _source_timestamp(record)
    if value is None:
        return None
    return date.fromisoformat(value)


def _reference_state(
    *,
    benchmark_return: Decimal | None,
    trend: Decimal | None,
    volatility: Decimal | None,
) -> ReferenceMarketState:
    if volatility is not None and volatility >= Decimal("8"):
        return ReferenceMarketState.HIGH_VOLATILITY
    if benchmark_return is not None:
        if benchmark_return <= Decimal("-8"):
            return ReferenceMarketState.CORRECTION
        if benchmark_return <= Decimal("-3"):
            return ReferenceMarketState.BEARISH_TREND
        if benchmark_return >= Decimal("5"):
            return ReferenceMarketState.BULLISH_TREND
        if benchmark_return >= Decimal("2"):
            return ReferenceMarketState.RECOVERY
        return ReferenceMarketState.SIDEWAYS
    if trend is not None:
        if trend >= Decimal("75"):
            return ReferenceMarketState.BULLISH_TREND
        if trend <= Decimal("35"):
            return ReferenceMarketState.BEARISH_TREND
        return ReferenceMarketState.SIDEWAYS
    return ReferenceMarketState.UNAVAILABLE


def _diagnostic_replayed_regime(
    snapshot: HistoricalMarketStateSnapshot,
) -> CanonicalRegime | None:
    if snapshot.source_completeness < Decimal("0.40"):
        return None
    if snapshot.reference_state in {
        ReferenceMarketState.BULLISH_TREND,
        ReferenceMarketState.RECOVERY,
    }:
        return CanonicalRegime.POSITIVE
    if snapshot.reference_state in {
        ReferenceMarketState.BEARISH_TREND,
        ReferenceMarketState.CORRECTION,
    }:
        return CanonicalRegime.NEGATIVE
    if snapshot.reference_state is ReferenceMarketState.HIGH_VOLATILITY:
        return CanonicalRegime.HIGH_VOLATILITY
    if snapshot.reference_state is ReferenceMarketState.SIDEWAYS:
        return CanonicalRegime.NEUTRAL
    return None


def _canonical_regime(value: str | None) -> CanonicalRegime:
    if value is None:
        return CanonicalRegime.UNAVAILABLE
    normalized = value.strip().upper()
    if normalized in {"BULL", "BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return CanonicalRegime.POSITIVE
    if normalized in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return CanonicalRegime.NEGATIVE
    if normalized in {"SIDEWAYS", "NEUTRAL"}:
        return CanonicalRegime.NEUTRAL
    return CanonicalRegime.UNKNOWN


def _same_direction(
    left: CanonicalRegime,
    right: CanonicalRegime | None,
) -> bool:
    if right is None:
        return False
    positive = {CanonicalRegime.POSITIVE, CanonicalRegime.STRONG_POSITIVE}
    negative = {CanonicalRegime.NEGATIVE, CanonicalRegime.STRONG_NEGATIVE}
    neutral = {CanonicalRegime.NEUTRAL, CanonicalRegime.SIDEWAYS}
    return (
        (left in positive and right in positive)
        or (left in negative and right in negative)
        or (left in neutral and right in neutral)
        or left is right
    )


def _episode_type(snapshot: HistoricalMarketStateSnapshot) -> MarketEpisodeType:
    if snapshot.reference_state is ReferenceMarketState.BULLISH_TREND:
        return MarketEpisodeType.BULLISH_TREND
    if snapshot.reference_state in {
        ReferenceMarketState.BEARISH_TREND,
        ReferenceMarketState.CORRECTION,
    }:
        return MarketEpisodeType.BEARISH_TREND
    if snapshot.reference_state is ReferenceMarketState.HIGH_VOLATILITY:
        return MarketEpisodeType.HIGH_VOLATILITY
    if snapshot.reference_state is ReferenceMarketState.SIDEWAYS:
        return MarketEpisodeType.RANGE_BOUND
    if snapshot.reference_state is ReferenceMarketState.RECOVERY:
        return MarketEpisodeType.RISK_ON
    return MarketEpisodeType.UNKNOWN


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {window.window: window for window in outcome.windows}
    for label in ("20d", "10d", "5d", "3d", "1d", "60d"):
        window = by_window.get(label)
        if (
            window is not None
            and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ):
            return window
    return outcome.windows[0] if outcome.windows else None


def _indicator(
    record: CandidateDecisionRecord, keys: tuple[str, ...]
) -> Decimal | None:
    normalized = {
        key.replace("_", "-").lower(): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        value = normalized.get(key.replace("_", "-").lower())
        if value is not None:
            try:
                return Decimal(str(value))
            except Exception:
                return None
    return None


def _text_indicator(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
) -> str | None:
    normalized = {
        key.replace("_", "-").lower(): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        value = normalized.get(key.replace("_", "-").lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _bool_indicator(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
) -> bool | None:
    value = _text_indicator(record, keys)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _int_indicator(
    record: CandidateDecisionRecord, keys: tuple[str, ...]
) -> int | None:
    value = _indicator(record, keys)
    return None if value is None else int(value)


def _is_default_neutral(
    record: CandidateDecisionRecord,
    snapshot: HistoricalMarketStateSnapshot,
) -> bool:
    return (
        record.market_regime or ""
    ).strip().upper() == "NEUTRAL" and snapshot.source_timestamp is None


def _has_missing_text(record: CandidateDecisionRecord) -> bool:
    text = " ".join(
        (
            record.data_quality,
            record.explanation,
            " ".join(record.rejection_reasons),
        )
    ).upper()
    return any(token in text for token in ("MISSING", "UNAVAILABLE", "INSUFFICIENT"))


def _regime_text(value: str | None) -> str:
    return (value or "UNAVAILABLE").strip().upper() or "UNAVAILABLE"


def _grade(value: Decimal) -> str:
    if value >= Decimal("0.80"):
        return "HIGH"
    if value >= Decimal("0.50"):
        return "MEDIUM"
    if value > _ZERO:
        return "LOW"
    return "UNAVAILABLE"


def _fallback_rate(
    fallbacks: tuple[FallbackAttribution, ...],
    rows: tuple[_AuditRow, ...],
) -> Decimal:
    return _rate(len(fallbacks), len(rows)) or _ZERO


def _selection_neutral_concentration(rows: tuple[_AuditRow, ...]) -> Decimal:
    return (
        _rate(
            sum(
                1
                for row in rows
                if _canonical_regime(row.record.market_regime)
                is CanonicalRegime.NEUTRAL
            ),
            len(rows),
        )
        or _ZERO
    )


def _top_decile_win_rate(rows: tuple[_AuditRow, ...]) -> Decimal | None:
    if not rows:
        return None
    sorted_rows = tuple(
        sorted(rows, key=lambda row: row.record.strategy_score, reverse=True)
    )
    count = max(1, int(len(sorted_rows) * 0.10))
    sample = sorted_rows[:count]
    return _rate(sum(1 for row in sample if row.profitable is True), len(sample))


def _roc_auc(
    scores: tuple[Decimal | None, ...], labels: tuple[bool, ...]
) -> Decimal | None:
    pairs = tuple(
        (score, label)
        for score, label in zip(scores, labels, strict=False)
        if score is not None
    )
    positives = tuple(score for score, label in pairs if label)
    negatives = tuple(score for score, label in pairs if not label)
    if not positives or not negatives:
        return None
    wins = _ZERO
    total = Decimal(len(positives) * len(negatives))
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += _ONE
            elif positive == negative:
                wins += Decimal("0.5")
    return (wins / total).quantize(_FOUR)


def _spearman(
    left: tuple[Decimal | None, ...],
    right: tuple[Decimal | None, ...],
) -> Decimal | None:
    pairs = tuple(
        (a, b)
        for a, b in zip(left, right, strict=False)
        if a is not None and b is not None
    )
    if len(pairs) < 3:
        return None
    return _pearson(
        _ranks(tuple(a for a, _ in pairs)), _ranks(tuple(b for _, b in pairs))
    )


def _ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return tuple(ranks)


def _pearson(left: tuple[Decimal, ...], right: tuple[Decimal, ...]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left, _ZERO) / Decimal(len(left))
    right_mean = sum(right, _ZERO) / Decimal(len(right))
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
    )
    left_var = sum(((a - left_mean) ** 2 for a in left), _ZERO)
    right_var = sum(((b - right_mean) ** 2 for b in right), _ZERO)
    if left_var == _ZERO or right_var == _ZERO:
        return None
    return (numerator / (left_var * right_var).sqrt()).quantize(_FOUR)


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _snapshot_status_lines(
    snapshots: tuple[HistoricalMarketStateSnapshot, ...],
) -> tuple[str, ...]:
    counts = Counter(item.reconstruction_status.value for item in snapshots)
    return tuple(f"- {key}: {value}" for key, value in sorted(counts.items())) or (
        "- none",
    )


def _inventory_lines(items: tuple[PersistenceInventoryItem, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.field}: {item.authoritative_or_reconstructed.value}, "
        f"coverage {item.coverage_count}, missing {_text(item.missing_rate)}"
        for item in items
    )


def _timestamp_summary_lines(
    items: tuple[TimestampAlignmentSummary, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.alignment.value}: count {item.count}, share "
        f"{_text(item.percentage)}, max stale {item.maximum_staleness_days}"
        for item in items
    ) or ("- none",)


def _fallback_lines(items: tuple[FallbackAttributionSummary, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.reason.value}: candidates {item.candidate_count}, completed "
        f"{item.completed_outcomes}, win rate {_text(item.win_rate)}"
        for item in items
    ) or ("- none",)


def _comparison_lines(item: StateComparisonSummary) -> tuple[str, ...]:
    return (
        f"- sample count: {item.sample_count}",
        f"- exact agreement: {_text(item.exact_regime_agreement)}",
        f"- directional agreement: {_text(item.directional_agreement)}",
        f"- neutral disagreement: {_text(item.neutral_disagreement_rate)}",
        (
            "- extreme-to-neutral collapse: "
            f"{_text(item.extreme_to_neutral_collapse_rate)}"
        ),
        f"- notes: {item.notes}",
    )


def _episode_lines(items: tuple[MarketStateEpisode, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.episode_type.value}: {item.start} to {item.end}, candidates "
        f"{item.candidate_count}, win {_text(item.win_rate)}"
        for item in items
    ) or ("- unavailable",)


def _selection_lines(
    items: tuple[CandidateSelectionDistribution, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.stage}: n {item.sample_count}, neutral share "
        f"{_text(item.neutral_share)}, bearish reference share "
        f"{_text(item.bearish_reference_share)}"
        for item in items
    )


def _classifier_replay_lines(
    items: tuple[ClassifierReplayResult, ...],
) -> tuple[str, ...]:
    counts = Counter(item.agreement.value for item in items)
    return tuple(f"- {key}: {value}" for key, value in sorted(counts.items())) or (
        "- none",
    )


def _counterfactual_lines(
    items: tuple[MarketStateCounterfactual, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.name}: n {item.sample_count}, auc {_text(item.score_auc)}, "
        f"top decile win {_text(item.top_decile_win_rate)}, avg return "
        f"{_text(item.average_forward_return)}"
        for item in items
    )


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _snapshot_dict(item: HistoricalMarketStateSnapshot) -> dict[str, str]:
    return {
        "as_of": item.as_of,
        "market_date": item.market_date or "",
        "source_timestamp": item.source_timestamp or "",
        "benchmark_symbol": item.benchmark_symbol or "",
        "benchmark_return_20d": _text(item.benchmark_return_20d),
        "reference_state": item.reference_state.value,
        "production_regime": item.production_regime or "",
        "source_completeness": str(item.source_completeness),
        "reconstruction_status": item.reconstruction_status.value,
        "missing_fields": ";".join(item.missing_fields),
    }


def _report_dict(report: MarketStatePersistenceAuditReport) -> dict[str, object]:
    return {
        "candidate_count": report.candidate_count,
        "market_dates_covered": report.market_dates_covered,
        "authoritative_snapshots_available": report.authoritative_snapshots_available,
        "fully_reconstructed_snapshots": report.fully_reconstructed_snapshots,
        "partially_reconstructed_snapshots": report.partially_reconstructed_snapshots,
        "unavailable_snapshots": report.unavailable_snapshots,
        "inventory": [asdict(item) for item in report.inventory],
        "snapshots": [asdict(item) for item in report.snapshots],
        "timestamp_summary": [asdict(item) for item in report.timestamp_summary],
        "fallback_summary": [asdict(item) for item in report.fallback_summary],
        "state_comparison": asdict(report.state_comparison),
        "episodes": [asdict(item) for item in report.episodes],
        "selection_effect": [asdict(item) for item in report.selection_effect],
        "classifier_replay": [asdict(item) for item in report.classifier_replay],
        "counterfactuals": [asdict(item) for item in report.counterfactuals],
        "decision": asdict(report.decision),
        "policy_integrity": {
            "recommendation_scores_unchanged": report.recommendation_scores_unchanged,
            "verdicts_unchanged": report.verdicts_unchanged,
            "timing_states_unchanged": report.timing_states_unchanged,
            "approvals_unchanged": report.approvals_unchanged,
            "trade_plans_unchanged": report.trade_plans_unchanged,
            "allocations_unchanged": report.allocations_unchanged,
            "production_regime_labels_unchanged": (
                report.production_regime_labels_unchanged
            ),
            "persisted_candidate_records_unchanged": (
                report.persisted_candidate_records_unchanged
            ),
        },
    }
