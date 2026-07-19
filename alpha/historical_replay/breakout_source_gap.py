from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, cast

from alpha.historical_replay.breakout_reference import (
    BreakoutReferenceReadinessStatus,
    BreakoutReferenceReconstructionRecord,
)

BREAKOUT_GAP_AUDIT_VERSION = "breakout-source-gap-audit-v1"
PRODUCTION_INFLUENCE = False

_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")
_READY_STATUSES = {
    BreakoutReferenceReadinessStatus.READY,
    BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED,
}
_EXISTING_SOURCE_RECOVERY = {
    "RECOVERABLE_EXISTING_SOURCE",
    "RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR",
    "RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR",
    "RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION",
}


class BreakoutGapCause(StrEnum):
    NO_ARCHIVE_RECORD = "NO_ARCHIVE_RECORD"
    ARCHIVE_RECORD_INCOMPLETE = "ARCHIVE_RECORD_INCOMPLETE"
    INSUFFICIENT_PRE_CANDIDATE_LOOKBACK = "INSUFFICIENT_PRE_CANDIDATE_LOOKBACK"
    PARTIAL_LOOKBACK_AVAILABLE = "PARTIAL_LOOKBACK_AVAILABLE"
    CANDIDATE_DATE_BAR_MISSING = "CANDIDATE_DATE_BAR_MISSING"
    MULTI_SESSION_GAP = "MULTI_SESSION_GAP"
    INVALID_OHLCV_SERIES = "INVALID_OHLCV_SERIES"
    DUPLICATE_OR_CONFLICTING_BARS = "DUPLICATE_OR_CONFLICTING_BARS"
    TIMEZONE_OR_SESSION_MISMATCH = "TIMEZONE_OR_SESSION_MISMATCH"
    SYMBOL_IDENTITY_UNRESOLVED = "SYMBOL_IDENTITY_UNRESOLVED"
    SYMBOL_CHANGE_UNRESOLVED = "SYMBOL_CHANGE_UNRESOLVED"
    LISTING_DATE_CONFLICT = "LISTING_DATE_CONFLICT"
    DELISTING_DATE_CONFLICT = "DELISTING_DATE_CONFLICT"
    CORPORATE_ACTION_AMBIGUITY = "CORPORATE_ACTION_AMBIGUITY"
    ADJUSTMENT_MODE_CONFLICT = "ADJUSTMENT_MODE_CONFLICT"
    AMBIGUOUS_DECISION_CUTOFF = "AMBIGUOUS_DECISION_CUTOFF"
    REFERENCE_METHOD_UNSUPPORTED = "REFERENCE_METHOD_UNSUPPORTED"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    SOURCE_RETRIEVAL_ERROR = "SOURCE_RETRIEVAL_ERROR"
    IMPLEMENTATION_PATH_GAP = "IMPLEMENTATION_PATH_GAP"
    LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY = (
        "LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY"
    )
    UNKNOWN_GAP_CAUSE = "UNKNOWN_GAP_CAUSE"


class BreakoutGapRecoveryClass(StrEnum):
    RECOVERABLE_EXISTING_SOURCE = "RECOVERABLE_EXISTING_SOURCE"
    RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR = (
        "RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR"
    )
    RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR = (
        "RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR"
    )
    RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION = (
        "RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION"
    )
    REQUIRES_NEW_EXTERNAL_SOURCE = "REQUIRES_NEW_EXTERNAL_SOURCE"
    LEGITIMATELY_UNRECOVERABLE = "LEGITIMATELY_UNRECOVERABLE"
    RECOVERY_UNCERTAIN = "RECOVERY_UNCERTAIN"


class BreakoutAttributionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BreakoutSourcePathDisposition(StrEnum):
    READY = "READY"
    TRUE_SOURCE_ABSENCE = "TRUE_SOURCE_ABSENCE"
    AVAILABLE_SOURCE_NOT_REACHED = "AVAILABLE_SOURCE_NOT_REACHED"
    AVAILABLE_SOURCE_REJECTED_CORRECTLY = "AVAILABLE_SOURCE_REJECTED_CORRECTLY"
    AVAILABLE_SOURCE_REJECTED_INCORRECTLY = "AVAILABLE_SOURCE_REJECTED_INCORRECTLY"
    SOURCE_PATH_UNCERTAIN = "SOURCE_PATH_UNCERTAIN"


class BreakoutMissingnessMechanism(StrEnum):
    MCAR_PLAUSIBLE = "MCAR_PLAUSIBLE"
    MAR_OBSERVED_STRUCTURE = "MAR_OBSERVED_STRUCTURE"
    MNAR_RISK = "MNAR_RISK"
    MIXED_MISSINGNESS = "MIXED_MISSINGNESS"
    INSUFFICIENT_TO_CLASSIFY = "INSUFFICIENT_TO_CLASSIFY"


class BreakoutReadySampleBiasConclusion(StrEnum):
    READY_SAMPLE_APPEARS_REPRESENTATIVE = "READY_SAMPLE_APPEARS_REPRESENTATIVE"
    READY_SAMPLE_HAS_MINOR_OBSERVED_BIAS = "READY_SAMPLE_HAS_MINOR_OBSERVED_BIAS"
    READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS = "READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS"
    READY_SAMPLE_HAS_SEVERE_SURVIVORSHIP_RISK = (
        "READY_SAMPLE_HAS_SEVERE_SURVIVORSHIP_RISK"
    )
    READY_SAMPLE_BIAS_CANNOT_BE_ASSESSED = "READY_SAMPLE_BIAS_CANNOT_BE_ASSESSED"


class BreakoutGapAuditConclusion(StrEnum):
    IMPLEMENTATION_RECOVERY_SHOULD_PRECEDE_NEW_DATA_SOURCE = (
        "IMPLEMENTATION_RECOVERY_SHOULD_PRECEDE_NEW_DATA_SOURCE"
    )
    IDENTITY_REPAIR_SHOULD_PRECEDE_NEW_DATA_SOURCE = (
        "IDENTITY_REPAIR_SHOULD_PRECEDE_NEW_DATA_SOURCE"
    )
    EXISTING_SOURCES_CANNOT_CLOSE_MATERIAL_GAPS = (
        "EXISTING_SOURCES_CANNOT_CLOSE_MATERIAL_GAPS"
    )
    NEW_HISTORICAL_SOURCE_REQUIRED = "NEW_HISTORICAL_SOURCE_REQUIRED"
    READY_SAMPLE_SUFFICIENT_FOR_RESTRICTED_VALIDATION = (
        "READY_SAMPLE_SUFFICIENT_FOR_RESTRICTED_VALIDATION"
    )
    READY_SAMPLE_TOO_BIASED_FOR_VALIDATION = "READY_SAMPLE_TOO_BIASED_FOR_VALIDATION"
    GAP_CAUSES_REQUIRE_FURTHER_DIAGNOSIS = "GAP_CAUSES_REQUIRE_FURTHER_DIAGNOSIS"


@dataclass(frozen=True, slots=True)
class BreakoutSourceProbe:
    source_provider: str = "PROJECT_ALPHA_CANONICAL_DAILY_PRICES"
    source_dataset: str = "data/ingestion.duckdb:daily_prices"
    source_query_attempted: str = ""
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    available_start_date: date | None = None
    available_end_date: date | None = None
    global_source_start_date: date | None = None
    global_source_end_date: date | None = None
    symbol_first_source_date: date | None = None
    symbol_last_source_date: date | None = None
    raw_archive_start_date: date | None = None
    raw_archive_end_date: date | None = None
    extracted_cache_start_date: date | None = None
    extracted_cache_end_date: date | None = None
    raw_archive_count: int = 0
    extracted_cache_count: int = 0
    candidate_date_bar_present: bool = False
    historical_symbol_query_used: bool = True
    current_symbol_only_query: bool = False
    fallback_source_has_data: bool = False
    source_cache_has_additional_data: bool = False
    off_by_one_boundary: bool = False
    valid_data_filtered_incorrectly: bool = False
    valid_data_rejected_correctly: bool = False
    minimum_lookback_larger_than_required: bool = False
    corporate_action_metadata_available_but_not_joined: bool = False
    supported_provider_omitted: bool = False
    date_format_mismatch: bool = False
    legacy_replay_run_identifier_mismatch: bool = False
    provenance_partial_status_needed: bool = False
    source_retrieval_error: str | None = None
    identity_resolution_status: str = "UNAVAILABLE"
    listing_date: date | None = None
    listing_date_evidence: str = "UNAVAILABLE"
    delisting_date: date | None = None
    delisting_date_evidence: str = "UNAVAILABLE"
    symbol_change_status: str = "UNAVAILABLE"
    corporate_action_status: str = "UNAVAILABLE"
    normalization_status: str = "UNAVAILABLE"
    cutoff_status: str = "UNAVAILABLE"
    provenance_status: str = "UNAVAILABLE"
    survival_status: str = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class BreakoutCandidateDiagnosticContext:
    candidate_id: str
    replay_run_id: str
    symbol: str
    candidate_date: date
    source: BreakoutSourceProbe
    sector: str | None = None
    liquidity_proxy: Decimal | None = None
    listing_age_days: int | None = None
    setup_type: str | None = None
    recommendation_verdict: str | None = None
    recommendation_score: Decimal | None = None
    price_component: Decimal | None = None
    volume_component: Decimal | None = None
    trend_component: Decimal | None = None
    entry_timing_state: str | None = None
    market_regime: str | None = None
    regime_confidence: Decimal | None = None
    breadth_state: str | None = None
    candidate_rank: int | None = None
    replay_version: str | None = None
    known_symbol_change_status: str = "UNAVAILABLE"
    inactive_or_delisted_status: str = "UNAVAILABLE"
    completed_outcome: bool = False
    forward_return: Decimal | None = None
    stop_hit: bool | None = None
    target_1_hit: bool | None = None


@dataclass(frozen=True, slots=True)
class BreakoutGapAttributionRecord:
    audit_version: str
    candidate_id: str
    replay_run_id: str
    historical_symbol: str
    instrument_identifier: str | None
    candidate_date: date
    readiness_status: BreakoutReferenceReadinessStatus
    bars_requested: int
    bars_returned: int
    bars_usable: int
    earliest_usable_bar: date | None
    latest_usable_bar: date | None
    context: BreakoutCandidateDiagnosticContext
    primary_gap_cause: BreakoutGapCause | None
    secondary_gap_causes: tuple[BreakoutGapCause, ...]
    recovery_class: BreakoutGapRecoveryClass | None
    attribution_confidence: BreakoutAttributionConfidence
    source_path_disposition: BreakoutSourcePathDisposition
    attribution_explanation: str
    production_influence: bool = PRODUCTION_INFLUENCE

    @property
    def ready(self) -> bool:
        return self.readiness_status in _READY_STATUSES


@dataclass(frozen=True, slots=True)
class BreakoutNumericDifference:
    dimension: str
    ready_sample: int
    unavailable_sample: int
    ready_mean: Decimal | None
    unavailable_mean: Decimal | None
    standardized_mean_difference: Decimal | None
    sufficient_sample: bool


@dataclass(frozen=True, slots=True)
class BreakoutDistributionDifference:
    dimension: str
    ready_sample: int
    unavailable_sample: int
    total_variation_distance: Decimal | None
    largest_difference_category: str | None
    largest_absolute_proportion_difference: Decimal | None
    sufficient_sample: bool


@dataclass(frozen=True, slots=True)
class BreakoutOutcomeDifference:
    metric: str
    ready_sample: int
    unavailable_sample: int
    ready_value: Decimal | None
    unavailable_value: Decimal | None
    absolute_difference: Decimal | None
    sufficient_sample: bool
    diagnostic_scope: str = "POST_CANDIDATE_DIAGNOSTIC_ONLY"


@dataclass(frozen=True, slots=True)
class BreakoutSymbolInclusion:
    symbol: str
    candidate_count: int
    ready_count: int
    inclusion_probability: Decimal


@dataclass(frozen=True, slots=True)
class BreakoutSelectionBiasReport:
    total_candidates: int
    ready_candidates: int
    unavailable_candidates: int
    unique_symbols: int
    ready_unique_symbols: int
    unavailable_unique_symbols: int
    candidate_inclusion_probability: Decimal
    numeric_differences: tuple[BreakoutNumericDifference, ...]
    distribution_differences: tuple[BreakoutDistributionDifference, ...]
    outcome_differences: tuple[BreakoutOutcomeDifference, ...]
    symbol_inclusion: tuple[BreakoutSymbolInclusion, ...]
    ready_symbol_hhi: Decimal | None
    unavailable_symbol_hhi: Decimal | None
    symbol_hhi_difference: Decimal | None
    repeated_symbol_warning: str
    missingness_mechanism: BreakoutMissingnessMechanism
    bias_conclusion: BreakoutReadySampleBiasConclusion
    minimum_sample: int
    warnings: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class BreakoutRecoveryScenario:
    recovery_class: BreakoutGapRecoveryClass
    candidate_count: int
    symbol_count: int
    year_range: tuple[int | None, int | None]
    proposed_authoritative_source: str
    required_action: str
    integrity_risks: tuple[str, ...]
    recovery_kind: str
    projected_readiness: Decimal


@dataclass(frozen=True, slots=True)
class BreakoutRecoveryReadinessReport:
    total_candidates: int
    current_ready_records: int
    current_readiness: Decimal
    recovery_distribution: tuple[tuple[str, int], ...]
    recoverable_existing_source: int
    recoverable_after_identity_repair: int
    recoverable_after_normalization_repair: int
    recoverable_after_cutoff_resolution: int
    requires_new_external_source: int
    legitimately_unrecoverable: int
    recovery_uncertain: int
    projected_ready_after_existing_source_recovery: int
    projected_readiness_after_existing_source_recovery: Decimal
    projected_readiness_if_new_source_records_remain_unavailable: Decimal
    scenarios: tuple[BreakoutRecoveryScenario, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class BreakoutGapGroupRow:
    group_by: str
    key: str
    candidate_count: int
    ready_count: int
    unavailable_count: int
    inclusion_probability: Decimal


@dataclass(frozen=True, slots=True)
class BreakoutSourceCoverageMatrix:
    records: tuple[BreakoutGapAttributionRecord, ...]
    supported_groupings: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class BreakoutSourceGapAuditReport:
    audit_version: str
    coverage: BreakoutSourceCoverageMatrix
    selection_bias: BreakoutSelectionBiasReport
    recovery: BreakoutRecoveryReadinessReport
    total_candidates: int
    ready_records: int
    unreconstructable_records: int
    overall_readiness: Decimal
    unique_affected_symbols: int
    affected_year_range: tuple[int | None, int | None]
    primary_gap_cause_distribution: tuple[tuple[str, int], ...]
    secondary_gap_cause_distribution: tuple[tuple[str, int], ...]
    true_source_absence_count: int
    implementation_path_gap_count: int
    identity_related_count: int
    corporate_action_related_count: int
    cutoff_ambiguity_count: int
    legitimately_insufficient_history_count: int
    unknown_cause_count: int
    conclusion: BreakoutGapAuditConclusion
    production_influence: bool = PRODUCTION_INFLUENCE


class BreakoutSourceGapAuditEngine:
    """Attribute immutable reconstruction gaps without rebuilding evidence."""

    def analyze(
        self,
        *,
        records: Sequence[BreakoutReferenceReconstructionRecord],
        contexts: Sequence[BreakoutCandidateDiagnosticContext],
        minimum_sample: int = 10,
    ) -> BreakoutSourceGapAuditReport:
        if minimum_sample < 2:
            raise ValueError("minimum_sample must be at least 2")
        context_index = {item.candidate_id: item for item in contexts}
        missing_context = tuple(
            record.candidate_id
            for record in records
            if record.candidate_id not in context_index
        )
        if missing_context:
            raise ValueError(
                "diagnostic context missing for candidate " + missing_context[0]
            )
        attributed = tuple(
            self.attribute(record, context_index[record.candidate_id])
            for record in sorted(records, key=_reference_sort_key)
        )
        selection = _selection_bias(attributed, minimum_sample)
        recovery = _recovery_readiness(attributed)
        unavailable = tuple(item for item in attributed if not item.ready)
        primary = _enum_counts(item.primary_gap_cause for item in unavailable)
        secondary = _enum_counts(
            cause for item in unavailable for cause in item.secondary_gap_causes
        )
        affected_years = tuple(
            sorted({item.candidate_date.year for item in unavailable})
        )
        conclusion = _audit_conclusion(selection, recovery)
        return BreakoutSourceGapAuditReport(
            audit_version=BREAKOUT_GAP_AUDIT_VERSION,
            coverage=BreakoutSourceCoverageMatrix(
                records=attributed,
                supported_groupings=SUPPORTED_GAP_GROUPINGS,
            ),
            selection_bias=selection,
            recovery=recovery,
            total_candidates=len(attributed),
            ready_records=sum(item.ready for item in attributed),
            unreconstructable_records=len(unavailable),
            overall_readiness=_rate(
                sum(item.ready for item in attributed), len(attributed)
            ),
            unique_affected_symbols=len(
                {item.historical_symbol for item in unavailable}
            ),
            affected_year_range=(
                affected_years[0] if affected_years else None,
                affected_years[-1] if affected_years else None,
            ),
            primary_gap_cause_distribution=primary,
            secondary_gap_cause_distribution=secondary,
            true_source_absence_count=sum(
                item.primary_gap_cause
                in {
                    BreakoutGapCause.NO_ARCHIVE_RECORD,
                    BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
                }
                for item in unavailable
            ),
            implementation_path_gap_count=sum(
                item.primary_gap_cause is BreakoutGapCause.IMPLEMENTATION_PATH_GAP
                for item in unavailable
            ),
            identity_related_count=sum(
                item.primary_gap_cause
                in {
                    BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED,
                    BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED,
                    BreakoutGapCause.LISTING_DATE_CONFLICT,
                    BreakoutGapCause.DELISTING_DATE_CONFLICT,
                }
                for item in unavailable
            ),
            corporate_action_related_count=sum(
                item.primary_gap_cause
                in {
                    BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
                    BreakoutGapCause.ADJUSTMENT_MODE_CONFLICT,
                }
                for item in unavailable
            ),
            cutoff_ambiguity_count=sum(
                item.primary_gap_cause is BreakoutGapCause.AMBIGUOUS_DECISION_CUTOFF
                for item in unavailable
            ),
            legitimately_insufficient_history_count=sum(
                item.primary_gap_cause
                is BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY
                or BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY
                in item.secondary_gap_causes
                for item in unavailable
            ),
            unknown_cause_count=sum(
                item.primary_gap_cause is BreakoutGapCause.UNKNOWN_GAP_CAUSE
                for item in unavailable
            ),
            conclusion=conclusion,
        )

    def attribute(
        self,
        record: BreakoutReferenceReconstructionRecord,
        context: BreakoutCandidateDiagnosticContext,
    ) -> BreakoutGapAttributionRecord:
        if record.candidate_id != context.candidate_id:
            raise ValueError("record and context candidate ids do not match")
        timestamps = record.provenance.source_bar_timestamps
        earliest = timestamps[0].date() if timestamps else None
        latest = timestamps[-1].date() if timestamps else None
        if record.readiness_status in _READY_STATUSES:
            return BreakoutGapAttributionRecord(
                audit_version=BREAKOUT_GAP_AUDIT_VERSION,
                candidate_id=record.candidate_id,
                replay_run_id=record.replay_run_id,
                historical_symbol=record.historical_symbol,
                instrument_identifier=record.instrument_identifier,
                candidate_date=record.candidate_observation_date,
                readiness_status=record.readiness_status,
                bars_requested=record.historical_bars_requested,
                bars_returned=record.historical_bars_available,
                bars_usable=record.usable_bars,
                earliest_usable_bar=earliest,
                latest_usable_bar=latest,
                context=context,
                primary_gap_cause=None,
                secondary_gap_causes=(),
                recovery_class=None,
                attribution_confidence=BreakoutAttributionConfidence.HIGH,
                source_path_disposition=BreakoutSourcePathDisposition.READY,
                attribution_explanation=(
                    "Point-in-time evidence passed reconstruction integrity."
                ),
            )
        primary, secondary, confidence = _attribute_causes(record, context)
        recovery = _recovery_class(primary, secondary, context)
        disposition = _source_path_disposition(primary, context)
        return BreakoutGapAttributionRecord(
            audit_version=BREAKOUT_GAP_AUDIT_VERSION,
            candidate_id=record.candidate_id,
            replay_run_id=record.replay_run_id,
            historical_symbol=record.historical_symbol,
            instrument_identifier=record.instrument_identifier,
            candidate_date=record.candidate_observation_date,
            readiness_status=record.readiness_status,
            bars_requested=record.historical_bars_requested,
            bars_returned=record.historical_bars_available,
            bars_usable=record.usable_bars,
            earliest_usable_bar=earliest,
            latest_usable_bar=latest,
            context=context,
            primary_gap_cause=primary,
            secondary_gap_causes=secondary,
            recovery_class=recovery,
            attribution_confidence=confidence,
            source_path_disposition=disposition,
            attribution_explanation=_attribution_explanation(
                primary, recovery, record, context
            ),
        )


def _attribute_causes(
    record: BreakoutReferenceReconstructionRecord,
    context: BreakoutCandidateDiagnosticContext,
) -> tuple[
    BreakoutGapCause, tuple[BreakoutGapCause, ...], BreakoutAttributionConfidence
]:
    status = record.readiness_status
    reasons = set(record.provenance.exclusion_reasons)
    source = context.source
    if source.source_retrieval_error:
        return (
            BreakoutGapCause.SOURCE_RETRIEVAL_ERROR,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.UNSUPPORTED_REFERENCE_METHOD:
        return (
            BreakoutGapCause.REFERENCE_METHOD_UNSUPPORTED,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF:
        return (
            BreakoutGapCause.AMBIGUOUS_DECISION_CUTOFF,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED:
        cause = (
            BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED
            if context.known_symbol_change_status == "KNOWN_CHANGE_UNRESOLVED"
            else BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED
        )
        return cause, (), BreakoutAttributionConfidence.HIGH
    if status is BreakoutReferenceReadinessStatus.LISTING_DATE_VIOLATION:
        return (
            BreakoutGapCause.LISTING_DATE_CONFLICT,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.DELISTING_DATE_VIOLATION:
        return (
            BreakoutGapCause.DELISTING_DATE_CONFLICT,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.PROVENANCE_INCOMPLETE:
        return (
            BreakoutGapCause.PROVENANCE_INCOMPLETE,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.TIMEZONE_MISMATCH:
        return (
            BreakoutGapCause.TIMEZONE_OR_SESSION_MISMATCH,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.ADJUSTMENT_MODE_MISMATCH:
        return (
            BreakoutGapCause.ADJUSTMENT_MODE_CONFLICT,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY:
        return (
            BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
            (),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES:
        if "DUPLICATE_BAR_TIMESTAMPS" in reasons:
            cause = BreakoutGapCause.DUPLICATE_OR_CONFLICTING_BARS
        elif any("SESSION" in reason or "EXCHANGE" in reason for reason in reasons):
            cause = BreakoutGapCause.TIMEZONE_OR_SESSION_MISMATCH
        else:
            cause = BreakoutGapCause.INVALID_OHLCV_SERIES
        return cause, (), BreakoutAttributionConfidence.HIGH
    if (
        source.fallback_source_has_data
        or source.source_cache_has_additional_data
        or source.off_by_one_boundary
        or source.valid_data_filtered_incorrectly
        or source.current_symbol_only_query
        or source.minimum_lookback_larger_than_required
        or source.corporate_action_metadata_available_but_not_joined
        or source.supported_provider_omitted
        or source.date_format_mismatch
        or source.legacy_replay_run_identifier_mismatch
        or source.provenance_partial_status_needed
    ):
        secondary: list[BreakoutGapCause] = []
        if source.current_symbol_only_query:
            secondary.append(BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED)
        if source.off_by_one_boundary:
            secondary.append(BreakoutGapCause.CANDIDATE_DATE_BAR_MISSING)
        if source.date_format_mismatch:
            secondary.append(BreakoutGapCause.TIMEZONE_OR_SESSION_MISMATCH)
        if source.provenance_partial_status_needed:
            secondary.append(BreakoutGapCause.PROVENANCE_INCOMPLETE)
        return (
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            tuple(secondary),
            BreakoutAttributionConfidence.HIGH,
        )
    if status is BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE:
        if (
            source.candidate_date_bar_present
            and source.symbol_first_source_date == context.candidate_date
        ):
            return (
                BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY,
                (),
                BreakoutAttributionConfidence.LOW,
            )
        if source.global_source_start_date is None:
            return (
                BreakoutGapCause.NO_ARCHIVE_RECORD,
                (),
                BreakoutAttributionConfidence.HIGH,
            )
        return (
            BreakoutGapCause.ARCHIVE_RECORD_INCOMPLETE,
            _candidate_bar_secondary(source),
            BreakoutAttributionConfidence.MEDIUM,
        )
    if status is BreakoutReferenceReadinessStatus.MISSING_BARS:
        return (
            BreakoutGapCause.MULTI_SESSION_GAP,
            (BreakoutGapCause.ARCHIVE_RECORD_INCOMPLETE,),
            BreakoutAttributionConfidence.MEDIUM,
        )
    if status is BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK:
        left_censored = (
            record.usable_bars > 0
            and source.global_source_start_date is not None
            and source.available_start_date == source.global_source_start_date
        )
        if left_censored:
            return (
                BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
                (
                    BreakoutGapCause.NO_ARCHIVE_RECORD,
                    BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,
                ),
                BreakoutAttributionConfidence.HIGH,
            )
        if (
            context.listing_age_days is not None
            and context.listing_age_days < record.historical_bars_requested
        ):
            return (
                BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY,
                (BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,),
                BreakoutAttributionConfidence.HIGH,
            )
        return (
            BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,
            (),
            BreakoutAttributionConfidence.MEDIUM,
        )
    if status is BreakoutReferenceReadinessStatus.RECONSTRUCTION_ERROR:
        return (
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            (),
            BreakoutAttributionConfidence.LOW,
        )
    return (
        BreakoutGapCause.UNKNOWN_GAP_CAUSE,
        (),
        BreakoutAttributionConfidence.LOW,
    )


def _candidate_bar_secondary(
    source: BreakoutSourceProbe,
) -> tuple[BreakoutGapCause, ...]:
    if source.candidate_date_bar_present:
        return ()
    return (BreakoutGapCause.CANDIDATE_DATE_BAR_MISSING,)


def _recovery_class(
    primary: BreakoutGapCause,
    secondary: tuple[BreakoutGapCause, ...],
    context: BreakoutCandidateDiagnosticContext,
) -> BreakoutGapRecoveryClass:
    source = context.source
    if primary is BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY:
        authoritative_listing_evidence = source.listing_date_evidence.upper() in {
            "AUTHORITATIVE",
            "OFFICIAL",
            "OFFICIAL_EFFECTIVE_DATE",
            "POINT_IN_TIME_SECURITY_MASTER",
        }
        return (
            BreakoutGapRecoveryClass.LEGITIMATELY_UNRECOVERABLE
            if source.listing_date is not None and authoritative_listing_evidence
            else BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN
        )
    if primary is BreakoutGapCause.IMPLEMENTATION_PATH_GAP:
        if BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED in secondary:
            return BreakoutGapRecoveryClass(
                "RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR"
            )
        if source.off_by_one_boundary:
            return BreakoutGapRecoveryClass(
                "RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION"
            )
        if source.valid_data_filtered_incorrectly:
            return BreakoutGapRecoveryClass(
                "RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR"
            )
        if source.date_format_mismatch:
            return BreakoutGapRecoveryClass(
                "RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR"
            )
        return BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE
    if primary in {
        BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED,
        BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED,
        BreakoutGapCause.LISTING_DATE_CONFLICT,
        BreakoutGapCause.DELISTING_DATE_CONFLICT,
    }:
        return (
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR
            if source.fallback_source_has_data
            else BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN
        )
    if primary is BreakoutGapCause.AMBIGUOUS_DECISION_CUTOFF:
        return (
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION
        )
    if primary in {
        BreakoutGapCause.INVALID_OHLCV_SERIES,
        BreakoutGapCause.DUPLICATE_OR_CONFLICTING_BARS,
        BreakoutGapCause.TIMEZONE_OR_SESSION_MISMATCH,
        BreakoutGapCause.ADJUSTMENT_MODE_CONFLICT,
        BreakoutGapCause.PROVENANCE_INCOMPLETE,
    }:
        return (
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR
            if source.fallback_source_has_data
            or source.source_cache_has_additional_data
            else BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN
        )
    if primary in {
        BreakoutGapCause.NO_ARCHIVE_RECORD,
        BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
        BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
    }:
        return BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE
    return BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN


def _source_path_disposition(
    primary: BreakoutGapCause,
    context: BreakoutCandidateDiagnosticContext,
) -> BreakoutSourcePathDisposition:
    source = context.source
    if primary in {
        BreakoutGapCause.NO_ARCHIVE_RECORD,
        BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
    }:
        return BreakoutSourcePathDisposition.TRUE_SOURCE_ABSENCE
    if primary is BreakoutGapCause.IMPLEMENTATION_PATH_GAP:
        if source.valid_data_filtered_incorrectly:
            return BreakoutSourcePathDisposition.AVAILABLE_SOURCE_REJECTED_INCORRECTLY
        return BreakoutSourcePathDisposition.AVAILABLE_SOURCE_NOT_REACHED
    if source.valid_data_rejected_correctly:
        return BreakoutSourcePathDisposition.AVAILABLE_SOURCE_REJECTED_CORRECTLY
    return BreakoutSourcePathDisposition.SOURCE_PATH_UNCERTAIN


def _attribution_explanation(
    primary: BreakoutGapCause,
    recovery: BreakoutGapRecoveryClass,
    record: BreakoutReferenceReconstructionRecord,
    context: BreakoutCandidateDiagnosticContext,
) -> str:
    source = context.source
    return (
        f"{primary.value}: status {record.readiness_status.value}; "
        f"usable bars {record.usable_bars}/{record.historical_bars_requested}; "
        "source range "
        f"{_date_range(source.available_start_date, source.available_end_date)}; "
        f"global archive range "
        f"{_date_range(source.global_source_start_date, source.global_source_end_date)}"
        "; "
        f"recovery {recovery.value}."
    )


def _selection_bias(
    records: tuple[BreakoutGapAttributionRecord, ...],
    minimum_sample: int,
) -> BreakoutSelectionBiasReport:
    ready = tuple(item for item in records if item.ready)
    unavailable = tuple(item for item in records if not item.ready)
    numeric_extractors: tuple[
        tuple[str, Callable[[BreakoutGapAttributionRecord], Decimal | None]], ...
    ] = (
        ("recommendation_score", lambda row: row.context.recommendation_score),
        ("candidate_date_ordinal", lambda row: Decimal(row.candidate_date.toordinal())),
        ("liquidity_proxy", lambda row: row.context.liquidity_proxy),
        ("listing_age_days", _listing_age_decimal),
        ("price_component", lambda row: row.context.price_component),
        ("volume_component", lambda row: row.context.volume_component),
        ("trend_component", lambda row: row.context.trend_component),
        ("regime_confidence", lambda row: row.context.regime_confidence),
        ("candidate_rank", _candidate_rank_decimal),
        ("bars_usable", lambda row: Decimal(row.bars_usable)),
    )
    numeric = tuple(
        _numeric_difference(name, ready, unavailable, extractor, minimum_sample)
        for name, extractor in numeric_extractors
    )
    categorical_extractors: tuple[
        tuple[str, Callable[[BreakoutGapAttributionRecord], str]], ...
    ] = (
        ("year", lambda row: str(row.candidate_date.year)),
        ("sector", lambda row: row.context.sector or "UNAVAILABLE"),
        ("liquidity_bucket", lambda row: _score_bucket(row.context.liquidity_proxy)),
        ("listing_age_bucket", _listing_age_bucket),
        ("setup_type", lambda row: row.context.setup_type or "UNAVAILABLE"),
        (
            "recommendation_verdict",
            lambda row: row.context.recommendation_verdict or "UNAVAILABLE",
        ),
        (
            "recommendation_score_bucket",
            lambda row: _score_bucket(row.context.recommendation_score),
        ),
        (
            "price_component_bucket",
            lambda row: _score_bucket(row.context.price_component),
        ),
        (
            "volume_component_bucket",
            lambda row: _score_bucket(row.context.volume_component),
        ),
        (
            "trend_component_bucket",
            lambda row: _score_bucket(row.context.trend_component),
        ),
        (
            "entry_timing_state",
            lambda row: row.context.entry_timing_state or "UNAVAILABLE",
        ),
        ("market_regime", lambda row: row.context.market_regime or "UNAVAILABLE"),
        (
            "regime_confidence_bucket",
            lambda row: _score_bucket(row.context.regime_confidence),
        ),
        ("breadth_state", lambda row: row.context.breadth_state or "UNAVAILABLE"),
        ("provider", lambda row: row.context.source.source_provider),
        ("lookback_requirement", lambda row: str(row.bars_requested)),
        (
            "symbol_change_status",
            lambda row: row.context.known_symbol_change_status,
        ),
        (
            "survival_or_continuity_status",
            lambda row: row.context.inactive_or_delisted_status,
        ),
        ("replay_version", lambda row: row.context.replay_version or "UNAVAILABLE"),
    )
    distributions = tuple(
        _distribution_difference(name, ready, unavailable, extractor, minimum_sample)
        for name, extractor in categorical_extractors
    )
    outcomes = _outcome_differences(ready, unavailable, minimum_sample)
    symbols: dict[str, list[BreakoutGapAttributionRecord]] = defaultdict(list)
    for row in records:
        symbols[row.historical_symbol].append(row)
    symbol_inclusion = tuple(
        BreakoutSymbolInclusion(
            symbol=symbol,
            candidate_count=len(rows),
            ready_count=sum(row.ready for row in rows),
            inclusion_probability=_rate(sum(row.ready for row in rows), len(rows)),
        )
        for symbol, rows in sorted(symbols.items())
    )
    missingness = _missingness_mechanism(distributions, records, minimum_sample)
    bias = _bias_conclusion(numeric, distributions, records, minimum_sample)
    ready_hhi = _symbol_hhi(ready)
    unavailable_hhi = _symbol_hhi(unavailable)
    return BreakoutSelectionBiasReport(
        total_candidates=len(records),
        ready_candidates=len(ready),
        unavailable_candidates=len(unavailable),
        unique_symbols=len(symbols),
        ready_unique_symbols=len({row.historical_symbol for row in ready}),
        unavailable_unique_symbols=len({row.historical_symbol for row in unavailable}),
        candidate_inclusion_probability=_rate(len(ready), len(records)),
        numeric_differences=numeric,
        distribution_differences=distributions,
        outcome_differences=outcomes,
        symbol_inclusion=symbol_inclusion,
        ready_symbol_hhi=ready_hhi,
        unavailable_symbol_hhi=unavailable_hhi,
        symbol_hhi_difference=(
            _quantize(abs(ready_hhi - unavailable_hhi))
            if ready_hhi is not None and unavailable_hhi is not None
            else None
        ),
        repeated_symbol_warning=(
            "Candidate rows are clustered by symbol; effect sizes are diagnostic "
            "and are not treated as independent observations."
        ),
        missingness_mechanism=missingness,
        bias_conclusion=bias,
        minimum_sample=minimum_sample,
        warnings=(
            "Outcome comparisons are post-candidate diagnostics and are not used "
            "to reconstruct evidence.",
            "Absence of a large observed difference is not proof of "
            "representativeness.",
            "Unavailable fields are retained as UNAVAILABLE and are not imputed.",
        ),
    )


def _numeric_difference(
    name: str,
    ready: tuple[BreakoutGapAttributionRecord, ...],
    unavailable: tuple[BreakoutGapAttributionRecord, ...],
    extractor: Callable[[BreakoutGapAttributionRecord], Decimal | None],
    minimum_sample: int,
) -> BreakoutNumericDifference:
    ready_values = tuple(
        value for row in ready if (value := extractor(row)) is not None
    )
    unavailable_values = tuple(
        value for row in unavailable if (value := extractor(row)) is not None
    )
    sufficient = (
        len(ready_values) >= minimum_sample
        and len(unavailable_values) >= minimum_sample
    )
    if not sufficient:
        return BreakoutNumericDifference(
            dimension=name,
            ready_sample=len(ready_values),
            unavailable_sample=len(unavailable_values),
            ready_mean=None,
            unavailable_mean=None,
            standardized_mean_difference=None,
            sufficient_sample=False,
        )
    ready_floats = tuple(float(value) for value in ready_values)
    unavailable_floats = tuple(float(value) for value in unavailable_values)
    ready_mean_float = fmean(ready_floats)
    unavailable_mean_float = fmean(unavailable_floats)
    pooled_variance = (pstdev(ready_floats) ** 2 + pstdev(unavailable_floats) ** 2) / 2
    if pooled_variance == 0:
        smd = 0.0 if ready_mean_float == unavailable_mean_float else None
    else:
        smd = (ready_mean_float - unavailable_mean_float) / pooled_variance**0.5
    return BreakoutNumericDifference(
        dimension=name,
        ready_sample=len(ready_values),
        unavailable_sample=len(unavailable_values),
        ready_mean=_decimal_float(ready_mean_float),
        unavailable_mean=_decimal_float(unavailable_mean_float),
        standardized_mean_difference=(None if smd is None else _decimal_float(smd)),
        sufficient_sample=True,
    )


def _distribution_difference(
    name: str,
    ready: tuple[BreakoutGapAttributionRecord, ...],
    unavailable: tuple[BreakoutGapAttributionRecord, ...],
    extractor: Callable[[BreakoutGapAttributionRecord], str],
    minimum_sample: int,
) -> BreakoutDistributionDifference:
    sufficient = len(ready) >= minimum_sample and len(unavailable) >= minimum_sample
    if not sufficient:
        return BreakoutDistributionDifference(
            dimension=name,
            ready_sample=len(ready),
            unavailable_sample=len(unavailable),
            total_variation_distance=None,
            largest_difference_category=None,
            largest_absolute_proportion_difference=None,
            sufficient_sample=False,
        )
    ready_counts = Counter(extractor(row) for row in ready)
    unavailable_counts = Counter(extractor(row) for row in unavailable)
    categories = tuple(sorted(set(ready_counts) | set(unavailable_counts)))
    differences = {
        category: abs(
            Decimal(ready_counts[category]) / Decimal(len(ready))
            - Decimal(unavailable_counts[category]) / Decimal(len(unavailable))
        )
        for category in categories
    }
    largest = max(categories, key=lambda item: (differences[item], item))
    total_variation = sum(differences.values(), _ZERO) / Decimal(2)
    return BreakoutDistributionDifference(
        dimension=name,
        ready_sample=len(ready),
        unavailable_sample=len(unavailable),
        total_variation_distance=_quantize(total_variation),
        largest_difference_category=largest,
        largest_absolute_proportion_difference=_quantize(differences[largest]),
        sufficient_sample=True,
    )


def _outcome_differences(
    ready: tuple[BreakoutGapAttributionRecord, ...],
    unavailable: tuple[BreakoutGapAttributionRecord, ...],
    minimum_sample: int,
) -> tuple[BreakoutOutcomeDifference, ...]:
    ready_completed = tuple(row for row in ready if row.context.completed_outcome)
    unavailable_completed = tuple(
        row for row in unavailable if row.context.completed_outcome
    )
    availability = _outcome_difference(
        "completed_outcome_availability",
        len(ready),
        len(unavailable),
        _rate(len(ready_completed), len(ready)),
        _rate(len(unavailable_completed), len(unavailable)),
        minimum_sample,
    )
    return (
        availability,
        _outcome_metric(
            "positive_20d_forward_return_rate",
            ready_completed,
            unavailable_completed,
            lambda row: (
                None
                if row.context.forward_return is None
                else Decimal(row.context.forward_return > _ZERO)
            ),
            minimum_sample,
            mean_values=True,
        ),
        _outcome_metric(
            "average_20d_forward_return",
            ready_completed,
            unavailable_completed,
            lambda row: row.context.forward_return,
            minimum_sample,
            mean_values=True,
        ),
        _outcome_metric(
            "target_1_hit_rate",
            ready_completed,
            unavailable_completed,
            lambda row: (
                None
                if row.context.target_1_hit is None
                else Decimal(row.context.target_1_hit)
            ),
            minimum_sample,
            mean_values=True,
        ),
        _outcome_metric(
            "stop_hit_rate",
            ready_completed,
            unavailable_completed,
            lambda row: (
                None if row.context.stop_hit is None else Decimal(row.context.stop_hit)
            ),
            minimum_sample,
            mean_values=True,
        ),
    )


def _outcome_metric(
    name: str,
    ready: tuple[BreakoutGapAttributionRecord, ...],
    unavailable: tuple[BreakoutGapAttributionRecord, ...],
    extractor: Callable[[BreakoutGapAttributionRecord], Decimal | None],
    minimum_sample: int,
    *,
    mean_values: bool,
) -> BreakoutOutcomeDifference:
    ready_values = tuple(
        value for row in ready if (value := extractor(row)) is not None
    )
    unavailable_values = tuple(
        value for row in unavailable if (value := extractor(row)) is not None
    )
    sufficient = (
        len(ready_values) >= minimum_sample
        and len(unavailable_values) >= minimum_sample
    )
    if not sufficient or not mean_values:
        return _outcome_difference(
            name,
            len(ready_values),
            len(unavailable_values),
            None,
            None,
            minimum_sample,
        )
    ready_value = sum(ready_values, _ZERO) / Decimal(len(ready_values))
    unavailable_value = sum(unavailable_values, _ZERO) / Decimal(
        len(unavailable_values)
    )
    return _outcome_difference(
        name,
        len(ready_values),
        len(unavailable_values),
        _quantize(ready_value),
        _quantize(unavailable_value),
        minimum_sample,
    )


def _outcome_difference(
    name: str,
    ready_sample: int,
    unavailable_sample: int,
    ready_value: Decimal | None,
    unavailable_value: Decimal | None,
    minimum_sample: int,
) -> BreakoutOutcomeDifference:
    sufficient = (
        ready_sample >= minimum_sample
        and unavailable_sample >= minimum_sample
        and ready_value is not None
        and unavailable_value is not None
    )
    return BreakoutOutcomeDifference(
        metric=name,
        ready_sample=ready_sample,
        unavailable_sample=unavailable_sample,
        ready_value=ready_value if sufficient else None,
        unavailable_value=unavailable_value if sufficient else None,
        absolute_difference=(
            _quantize(abs(ready_value - unavailable_value))
            if sufficient and ready_value is not None and unavailable_value is not None
            else None
        ),
        sufficient_sample=sufficient,
    )


def _missingness_mechanism(
    distributions: tuple[BreakoutDistributionDifference, ...],
    records: tuple[BreakoutGapAttributionRecord, ...],
    minimum_sample: int,
) -> BreakoutMissingnessMechanism:
    ready = sum(item.ready for item in records)
    unavailable = len(records) - ready
    if ready < minimum_sample or unavailable < minimum_sample:
        return BreakoutMissingnessMechanism.INSUFFICIENT_TO_CLASSIFY
    by_name = {item.dimension: item for item in distributions}
    year = _distance(by_name.get("year"))
    survival = _distance(by_name.get("survival_or_continuity_status"))
    symbol_change = _distance(by_name.get("symbol_change_status"))
    observed = max(
        (_distance(item) for item in distributions if item.sufficient_sample),
        default=_ZERO,
    )
    latent_risk = any(
        item.primary_gap_cause
        in {
            BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
            BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED,
            BreakoutGapCause.MULTI_SESSION_GAP,
        }
        for item in records
        if not item.ready
    )
    if observed >= Decimal("0.05") and (
        survival >= Decimal("0.10") or symbol_change >= Decimal("0.10")
    ):
        return BreakoutMissingnessMechanism.MIXED_MISSINGNESS
    if year >= Decimal("0.05") or observed >= Decimal("0.05"):
        return (
            BreakoutMissingnessMechanism.MIXED_MISSINGNESS
            if latent_risk and survival >= Decimal("0.05")
            else BreakoutMissingnessMechanism.MAR_OBSERVED_STRUCTURE
        )
    if latent_risk:
        return BreakoutMissingnessMechanism.MNAR_RISK
    return BreakoutMissingnessMechanism.MCAR_PLAUSIBLE


def _bias_conclusion(
    numeric: tuple[BreakoutNumericDifference, ...],
    distributions: tuple[BreakoutDistributionDifference, ...],
    records: tuple[BreakoutGapAttributionRecord, ...],
    minimum_sample: int,
) -> BreakoutReadySampleBiasConclusion:
    ready = sum(item.ready for item in records)
    unavailable = len(records) - ready
    if ready < minimum_sample or unavailable < minimum_sample:
        return BreakoutReadySampleBiasConclusion.READY_SAMPLE_BIAS_CANNOT_BE_ASSESSED
    max_smd = max(
        (
            abs(item.standardized_mean_difference)
            for item in numeric
            if item.standardized_mean_difference is not None
        ),
        default=_ZERO,
    )
    by_name = {item.dimension: item for item in distributions}
    max_distance = max(
        (_distance(item) for item in distributions if item.sufficient_sample),
        default=_ZERO,
    )
    survival = _distance(by_name.get("survival_or_continuity_status"))
    if survival >= Decimal("0.25") and _rate(ready, len(records)) < Decimal("0.60"):
        return (
            BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_SEVERE_SURVIVORSHIP_RISK
        )
    if max_smd >= Decimal("0.25") or max_distance >= Decimal("0.10"):
        return BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS
    if max_smd >= Decimal("0.10") or max_distance >= Decimal("0.05"):
        return BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_MINOR_OBSERVED_BIAS
    return BreakoutReadySampleBiasConclusion.READY_SAMPLE_APPEARS_REPRESENTATIVE


def _recovery_readiness(
    records: tuple[BreakoutGapAttributionRecord, ...],
) -> BreakoutRecoveryReadinessReport:
    ready = sum(item.ready for item in records)
    unavailable = tuple(item for item in records if not item.ready)
    counts = Counter(
        item.recovery_class.value
        for item in unavailable
        if item.recovery_class is not None
    )
    existing = sum(counts[name] for name in _EXISTING_SOURCE_RECOVERY)
    projected = ready + existing
    scenarios = tuple(
        _recovery_scenario(recovery_class, unavailable, ready, len(records))
        for recovery_class in BreakoutGapRecoveryClass
        if counts[recovery_class.value] > 0
    )
    return BreakoutRecoveryReadinessReport(
        total_candidates=len(records),
        current_ready_records=ready,
        current_readiness=_rate(ready, len(records)),
        recovery_distribution=tuple(sorted(counts.items())),
        recoverable_existing_source=counts[
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE.value
        ],
        recoverable_after_identity_repair=counts[
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR.value
        ],
        recoverable_after_normalization_repair=counts[
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR.value
        ],
        recoverable_after_cutoff_resolution=counts[
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION.value
        ],
        requires_new_external_source=counts[
            BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE.value
        ],
        legitimately_unrecoverable=counts[
            BreakoutGapRecoveryClass.LEGITIMATELY_UNRECOVERABLE.value
        ],
        recovery_uncertain=counts[BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN.value],
        projected_ready_after_existing_source_recovery=projected,
        projected_readiness_after_existing_source_recovery=_rate(
            projected, len(records)
        ),
        projected_readiness_if_new_source_records_remain_unavailable=_rate(
            projected, len(records)
        ),
        scenarios=scenarios,
    )


def _recovery_scenario(
    recovery_class: BreakoutGapRecoveryClass,
    records: tuple[BreakoutGapAttributionRecord, ...],
    ready: int,
    total: int,
) -> BreakoutRecoveryScenario:
    selected = tuple(item for item in records if item.recovery_class is recovery_class)
    years = tuple(sorted({item.candidate_date.year for item in selected}))
    existing = recovery_class.value in _EXISTING_SOURCE_RECOVERY
    source, action, risks, kind = _recovery_details(recovery_class)
    projected = ready + (len(selected) if existing else 0)
    return BreakoutRecoveryScenario(
        recovery_class=recovery_class,
        candidate_count=len(selected),
        symbol_count=len({item.historical_symbol for item in selected}),
        year_range=(years[0] if years else None, years[-1] if years else None),
        proposed_authoritative_source=source,
        required_action=action,
        integrity_risks=risks,
        recovery_kind=kind,
        projected_readiness=_rate(projected, total),
    )


def _recovery_details(
    recovery_class: BreakoutGapRecoveryClass,
) -> tuple[str, str, tuple[str, ...], str]:
    if recovery_class is BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE:
        return (
            "existing repository source identified by the source probe",
            "route the existing authoritative source through the "
            "reconstruction service",
            ("source precedence", "duplicate-bar reconciliation"),
            "CODE_REPAIR",
        )
    if (
        recovery_class
        is BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR
    ):
        return (
            "existing price archive plus point-in-time identity evidence",
            "repair effective-dated historical symbol identity before reconstruction",
            ("symbol reuse", "current-symbol leakage", "listing interval"),
            "IDENTITY_REPAIR",
        )
    if recovery_class is BreakoutGapRecoveryClass(
        "RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR"
    ):
        return (
            "existing canonical or cached archive",
            "repair deterministic normalization while retaining all exclusions",
            ("mixed adjustment modes", "OHLCV validity", "duplicate bars"),
            "NORMALIZATION_REPAIR",
        )
    if (
        recovery_class
        is BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION
    ):
        return (
            "existing source with independently proven decision timing",
            "resolve timestamp evidence without changing the cutoff policy",
            ("candidate-close leakage", "session boundary ambiguity"),
            "CUTOFF_EVIDENCE_REPAIR",
        )
    if recovery_class is BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE:
        return (
            "unavailable in current repository inventory",
            "acquire authoritative pre-boundary OHLCV or corporate-action "
            "evidence later",
            (
                "licensing",
                "identity continuity",
                "adjustment consistency",
                "provenance",
            ),
            "DATA_ACQUISITION_REQUIRED",
        )
    if recovery_class is BreakoutGapRecoveryClass.LEGITIMATELY_UNRECOVERABLE:
        return (
            "none",
            "retain explicit insufficient-history status",
            ("do not invent pre-listing or non-trading history",),
            "NO_RECOVERY_ALLOWED",
        )
    return (
        "not established",
        "collect stronger identity, suspension, archive, or source-path evidence",
        ("misclassification risk", "unproven source completeness"),
        "FURTHER_DIAGNOSIS",
    )


def _audit_conclusion(
    selection: BreakoutSelectionBiasReport,
    recovery: BreakoutRecoveryReadinessReport,
) -> BreakoutGapAuditConclusion:
    if (
        recovery.recoverable_existing_source
        + recovery.recoverable_after_normalization_repair
        > 0
    ):
        return BreakoutGapAuditConclusion(
            "IMPLEMENTATION_RECOVERY_SHOULD_PRECEDE_NEW_DATA_SOURCE"
        )
    if recovery.recoverable_after_identity_repair > 0:
        return BreakoutGapAuditConclusion.IDENTITY_REPAIR_SHOULD_PRECEDE_NEW_DATA_SOURCE
    if recovery.requires_new_external_source > 0:
        return BreakoutGapAuditConclusion.NEW_HISTORICAL_SOURCE_REQUIRED
    if selection.bias_conclusion in {
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS,
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_SEVERE_SURVIVORSHIP_RISK,
    }:
        return BreakoutGapAuditConclusion.READY_SAMPLE_TOO_BIASED_FOR_VALIDATION
    if (
        selection.bias_conclusion
        is BreakoutReadySampleBiasConclusion.READY_SAMPLE_APPEARS_REPRESENTATIVE
        and selection.candidate_inclusion_probability >= Decimal("0.80")
    ):
        return (
            BreakoutGapAuditConclusion.READY_SAMPLE_SUFFICIENT_FOR_RESTRICTED_VALIDATION
        )
    if recovery.recovery_uncertain > 0:
        return BreakoutGapAuditConclusion.GAP_CAUSES_REQUIRE_FURTHER_DIAGNOSIS
    return BreakoutGapAuditConclusion.EXISTING_SOURCES_CANNOT_CLOSE_MATERIAL_GAPS


SUPPORTED_GAP_GROUPINGS = (
    "year",
    "symbol",
    "sector",
    "provider",
    "primary-cause",
    "secondary-cause",
    "recovery-class",
    "market-regime",
    "setup-type",
    "entry-timing-state",
    "replay-version",
)


def group_breakout_gap_records(
    records: Sequence[BreakoutGapAttributionRecord],
    group_by: str,
) -> tuple[BreakoutGapGroupRow, ...]:
    normalized = group_by.strip().lower().replace("_", "-")
    if normalized not in SUPPORTED_GAP_GROUPINGS:
        allowed = ", ".join(SUPPORTED_GAP_GROUPINGS)
        raise ValueError(f"unsupported grouping {group_by!r}; choose one of: {allowed}")
    grouped: dict[str, list[BreakoutGapAttributionRecord]] = defaultdict(list)
    for record in records:
        keys = _group_keys(record, normalized)
        for key in keys:
            grouped[key].append(record)
    return tuple(
        BreakoutGapGroupRow(
            group_by=normalized,
            key=key,
            candidate_count=len(rows),
            ready_count=sum(row.ready for row in rows),
            unavailable_count=sum(not row.ready for row in rows),
            inclusion_probability=_rate(sum(row.ready for row in rows), len(rows)),
        )
        for key, rows in sorted(grouped.items())
    )


def _group_keys(record: BreakoutGapAttributionRecord, group_by: str) -> tuple[str, ...]:
    if group_by == "year":
        return (str(record.candidate_date.year),)
    if group_by == "symbol":
        return (record.historical_symbol,)
    if group_by == "sector":
        return (record.context.sector or "UNAVAILABLE",)
    if group_by == "provider":
        return (record.context.source.source_provider,)
    if group_by == "primary-cause":
        return (
            record.primary_gap_cause.value if record.primary_gap_cause else "READY",
        )
    if group_by == "secondary-cause":
        return tuple(item.value for item in record.secondary_gap_causes) or ("NONE",)
    if group_by == "recovery-class":
        return (record.recovery_class.value if record.recovery_class else "READY",)
    if group_by == "market-regime":
        return (record.context.market_regime or "UNAVAILABLE",)
    if group_by == "setup-type":
        return (record.context.setup_type or "UNAVAILABLE",)
    if group_by == "entry-timing-state":
        return (record.context.entry_timing_state or "UNAVAILABLE",)
    return (record.context.replay_version or "UNAVAILABLE",)


def filter_breakout_gap_records(
    records: Sequence[BreakoutGapAttributionRecord],
    *,
    cause: BreakoutGapCause | None = None,
    recovery_class: BreakoutGapRecoveryClass | None = None,
    provider: str | None = None,
    symbol: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    year: int | None = None,
    limit: int | None = None,
) -> tuple[BreakoutGapAttributionRecord, ...]:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    normalized_provider = provider.strip().upper() if provider else None
    normalized_symbol = symbol.strip().upper() if symbol else None
    filtered = tuple(
        row
        for row in records
        if cause is None or row.primary_gap_cause is cause
        if recovery_class is None or row.recovery_class is recovery_class
        if normalized_provider is None
        or row.context.source.source_provider.upper() == normalized_provider
        if normalized_symbol is None or row.historical_symbol == normalized_symbol
        if from_date is None or row.candidate_date >= from_date
        if to_date is None or row.candidate_date <= to_date
        if year is None or row.candidate_date.year == year
    )
    return filtered if limit is None else filtered[:limit]


def parse_breakout_gap_cause(value: str) -> BreakoutGapCause:
    normalized = value.strip().upper().replace("-", "_")
    try:
        return BreakoutGapCause(normalized)
    except ValueError as error:
        allowed = ", ".join(item.value for item in BreakoutGapCause)
        raise ValueError(
            f"unsupported gap cause {value!r}; choose one of: {allowed}"
        ) from error


def parse_breakout_recovery_class(value: str) -> BreakoutGapRecoveryClass:
    normalized = value.strip().upper().replace("-", "_")
    try:
        return BreakoutGapRecoveryClass(normalized)
    except ValueError as error:
        allowed = ", ".join(item.value for item in BreakoutGapRecoveryClass)
        raise ValueError(
            f"unsupported recovery class {value!r}; choose one of: {allowed}"
        ) from error


def render_breakout_source_gap_audit(
    report: BreakoutSourceGapAuditReport,
) -> tuple[str, ...]:
    recovery = report.recovery
    return (
        "Breakout Source-Gap Attribution Audit",
        f"Audit Version: {report.audit_version}",
        f"Total Candidates: {report.total_candidates}",
        f"Ready Records: {report.ready_records}",
        f"Unreconstructable Records: {report.unreconstructable_records}",
        f"Overall Readiness: {_pct(report.overall_readiness)}",
        f"Unique Affected Symbols: {report.unique_affected_symbols}",
        f"Affected Year Range: {_year_range(report.affected_year_range)}",
        "Primary Gap Causes: " + _counts(report.primary_gap_cause_distribution),
        "Secondary Gap Causes: " + _counts(report.secondary_gap_cause_distribution),
        f"True Source Absence: {report.true_source_absence_count}",
        f"Implementation-Path Gaps: {report.implementation_path_gap_count}",
        f"Identity-Related: {report.identity_related_count}",
        f"Corporate-Action-Related: {report.corporate_action_related_count}",
        f"Cutoff Ambiguity: {report.cutoff_ambiguity_count}",
        "Legitimately Insufficient Trading History: "
        f"{report.legitimately_insufficient_history_count}",
        f"Unknown Cause: {report.unknown_cause_count}",
        f"Recoverable Using Existing Sources: {_existing_source_recoverable(recovery)}",
        "Recoverable After Identity Repair: "
        f"{recovery.recoverable_after_identity_repair}",
        f"Requires New External Source: {recovery.requires_new_external_source}",
        f"Legitimately Unrecoverable: {recovery.legitimately_unrecoverable}",
        f"Recovery Uncertain: {recovery.recovery_uncertain}",
        f"Ready-Sample Bias Conclusion: {report.selection_bias.bias_conclusion.value}",
        f"Missingness Mechanism: {report.selection_bias.missingness_mechanism.value}",
        "Projected Readiness After Existing-Source Recovery: "
        f"{_pct(recovery.projected_readiness_after_existing_source_recovery)}",
        "Projected Readiness If New-Source Records Remain Unavailable: "
        f"{_pct(recovery.projected_readiness_if_new_source_records_remain_unavailable)}",
        f"Overall Next-Step Conclusion: {report.conclusion.value}",
        "No reconstruction, classifier, recommendation, approval, timing, stop, "
        "target, or production policy changed.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_selection_bias(
    report: BreakoutSelectionBiasReport,
) -> tuple[str, ...]:
    numeric = tuple(
        f"- {item.dimension}: ready n={item.ready_sample}, unavailable "
        f"n={item.unavailable_sample}, means {_optional(item.ready_mean)} vs "
        f"{_optional(item.unavailable_mean)}, SMD "
        f"{_optional(item.standardized_mean_difference)}"
        for item in report.numeric_differences
    )
    distributions = tuple(
        f"- {item.dimension}: n={item.ready_sample}/{item.unavailable_sample}, "
        f"TV distance {_optional(item.total_variation_distance)}, largest "
        f"{item.largest_difference_category or 'unavailable'} "
        f"({_optional(item.largest_absolute_proportion_difference)})"
        for item in report.distribution_differences
    )
    outcomes = tuple(
        f"- {item.metric}: n={item.ready_sample}/{item.unavailable_sample}, "
        f"ready {_optional(item.ready_value)}, unavailable "
        f"{_optional(item.unavailable_value)}, difference "
        f"{_optional(item.absolute_difference)}"
        for item in report.outcome_differences
    )
    return (
        "Breakout Ready-vs-Unavailable Selection-Bias Audit",
        f"Total Candidates: {report.total_candidates}",
        "Ready / Unavailable: "
        f"{report.ready_candidates} / {report.unavailable_candidates}",
        "Candidate Inclusion Probability: "
        f"{_pct(report.candidate_inclusion_probability)}",
        "Unique Symbols Ready / Unavailable: "
        f"{report.ready_unique_symbols} / {report.unavailable_unique_symbols}",
        f"Ready Symbol HHI: {_optional(report.ready_symbol_hhi)}",
        f"Unavailable Symbol HHI: {_optional(report.unavailable_symbol_hhi)}",
        f"Absolute Symbol HHI Difference: {_optional(report.symbol_hhi_difference)}",
        report.repeated_symbol_warning,
        "Pre-Outcome Numeric Effect Sizes:",
        *numeric,
        "Pre-Outcome Distribution Differences:",
        *distributions,
        "Post-Candidate Outcome Diagnostics (not used for reconstruction):",
        *outcomes,
        f"Missingness Mechanism: {report.missingness_mechanism.value}",
        f"Ready-Sample Bias Conclusion: {report.bias_conclusion.value}",
        *tuple(f"Warning: {warning}" for warning in report.warnings),
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_recovery_readiness(
    report: BreakoutRecoveryReadinessReport,
) -> tuple[str, ...]:
    scenarios = tuple(
        f"- {item.recovery_class.value}: candidates {item.candidate_count}, "
        f"symbols {item.symbol_count}, years {_year_range(item.year_range)}, "
        f"kind {item.recovery_kind}; source {item.proposed_authoritative_source}; "
        f"action {item.required_action}; projected readiness "
        f"{_pct(item.projected_readiness)}"
        for item in report.scenarios
    )
    return (
        "Breakout Recovery Readiness Audit",
        f"Total Candidates: {report.total_candidates}",
        f"Current Ready Records: {report.current_ready_records}",
        f"Current Readiness: {_pct(report.current_readiness)}",
        "Recovery Distribution: " + _counts(report.recovery_distribution),
        f"Existing Source Direct: {report.recoverable_existing_source}",
        f"Identity Repair: {report.recoverable_after_identity_repair}",
        f"Normalization Repair: {report.recoverable_after_normalization_repair}",
        f"Cutoff Resolution: {report.recoverable_after_cutoff_resolution}",
        f"New External Source Required: {report.requires_new_external_source}",
        f"Legitimately Unrecoverable: {report.legitimately_unrecoverable}",
        f"Recovery Uncertain: {report.recovery_uncertain}",
        "Projected Ready After Existing-Source Recovery: "
        f"{report.projected_ready_after_existing_source_recovery}",
        "Projected Readiness After Existing-Source Recovery: "
        f"{_pct(report.projected_readiness_after_existing_source_recovery)}",
        "Scenarios are deterministic feasibility cases, not recovery promises.",
        *scenarios,
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_source_coverage(
    matrix: BreakoutSourceCoverageMatrix,
    *,
    group_by: str = "provider",
) -> tuple[str, ...]:
    groups = group_breakout_gap_records(matrix.records, group_by)
    lines = tuple(
        f"- {item.key}: candidates {item.candidate_count}, ready "
        f"{item.ready_count}, unavailable {item.unavailable_count}, inclusion "
        f"{_pct(item.inclusion_probability)}"
        for item in groups
    )
    return (
        "Breakout Source Coverage Matrix",
        f"Candidate Rows: {len(matrix.records)}",
        f"Grouped By: {group_by.strip().lower().replace('_', '-')}",
        *lines,
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_gap_sample(
    records: Sequence[BreakoutGapAttributionRecord],
) -> tuple[str, ...]:
    lines = tuple(
        f"- {item.historical_symbol} {item.candidate_date}: "
        f"status={item.readiness_status.value}; primary="
        f"{item.primary_gap_cause.value if item.primary_gap_cause else 'READY'}; "
        "secondary="
        f"{','.join(cause.value for cause in item.secondary_gap_causes) or 'NONE'}; "
        f"bars={item.bars_usable}/{item.bars_requested}; recovery="
        f"{item.recovery_class.value if item.recovery_class else 'NONE'}; "
        f"confidence={item.attribution_confidence.value}"
        for item in records
    )
    return (
        "Breakout Gap Attribution Sample",
        f"Records Shown: {len(records)}",
        *lines,
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_gap_groups(
    records: Sequence[BreakoutGapAttributionRecord],
    group_by: str,
) -> tuple[str, ...]:
    return tuple(
        f"- {row.key}: candidates {row.candidate_count}, ready {row.ready_count}, "
        f"unavailable {row.unavailable_count}, inclusion "
        f"{_pct(row.inclusion_probability)}"
        for row in group_breakout_gap_records(records, group_by)
    )


def export_breakout_gap_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def export_breakout_gap_csv(
    records: Sequence[BreakoutGapAttributionRecord],
    path: Path,
) -> None:
    rows = tuple(
        _flat_record(item) for item in sorted(records, key=_attribution_sort_key)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(rows[0].keys()) if rows else _CSV_FIELDS
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


_CSV_FIELDS = (
    "candidate_id",
    "replay_run_id",
    "historical_symbol",
    "instrument_identifier",
    "candidate_date",
    "readiness_status",
    "source_provider",
    "source_query_attempted",
    "requested_start_date",
    "requested_end_date",
    "available_start_date",
    "available_end_date",
    "bars_requested",
    "bars_returned",
    "bars_usable",
    "earliest_usable_bar",
    "latest_usable_bar",
    "identity_resolution_status",
    "corporate_action_status",
    "normalization_status",
    "cutoff_status",
    "provenance_status",
    "primary_gap_cause",
    "secondary_gap_causes",
    "recovery_class",
    "attribution_confidence",
    "source_path_disposition",
)


def _flat_record(item: BreakoutGapAttributionRecord) -> dict[str, object]:
    source = item.context.source
    return {
        "candidate_id": item.candidate_id,
        "replay_run_id": item.replay_run_id,
        "historical_symbol": item.historical_symbol,
        "instrument_identifier": item.instrument_identifier,
        "candidate_date": item.candidate_date.isoformat(),
        "readiness_status": item.readiness_status.value,
        "source_provider": source.source_provider,
        "source_query_attempted": source.source_query_attempted,
        "requested_start_date": _date_text(source.requested_start_date),
        "requested_end_date": _date_text(source.requested_end_date),
        "available_start_date": _date_text(source.available_start_date),
        "available_end_date": _date_text(source.available_end_date),
        "bars_requested": item.bars_requested,
        "bars_returned": item.bars_returned,
        "bars_usable": item.bars_usable,
        "earliest_usable_bar": _date_text(item.earliest_usable_bar),
        "latest_usable_bar": _date_text(item.latest_usable_bar),
        "identity_resolution_status": source.identity_resolution_status,
        "corporate_action_status": source.corporate_action_status,
        "normalization_status": source.normalization_status,
        "cutoff_status": source.cutoff_status,
        "provenance_status": source.provenance_status,
        "primary_gap_cause": (
            item.primary_gap_cause.value if item.primary_gap_cause else None
        ),
        "secondary_gap_causes": ";".join(
            cause.value for cause in item.secondary_gap_causes
        ),
        "recovery_class": item.recovery_class.value if item.recovery_class else None,
        "attribution_confidence": item.attribution_confidence.value,
        "source_path_disposition": item.source_path_disposition.value,
    }


def _listing_age_decimal(
    row: BreakoutGapAttributionRecord,
) -> Decimal | None:
    return (
        None
        if row.context.listing_age_days is None
        else Decimal(row.context.listing_age_days)
    )


def _candidate_rank_decimal(
    row: BreakoutGapAttributionRecord,
) -> Decimal | None:
    return (
        None
        if row.context.candidate_rank is None
        else Decimal(row.context.candidate_rank)
    )


def _listing_age_bucket(row: BreakoutGapAttributionRecord) -> str:
    age = row.context.listing_age_days
    if age is None:
        return "UNAVAILABLE"
    if age < 90:
        return "LT_90_DAYS"
    if age < 365:
        return "90_TO_364_DAYS"
    if age < 1825:
        return "1_TO_5_YEARS"
    return "5_PLUS_YEARS"


def _score_bucket(value: Decimal | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    normalized = value * _HUNDRED if abs(value) <= Decimal("1.5") else value
    if normalized < Decimal("25"):
        return "VERY_LOW"
    if normalized < Decimal("50"):
        return "LOW"
    if normalized < Decimal("75"):
        return "HIGH"
    return "VERY_HIGH"


def _symbol_hhi(records: Sequence[BreakoutGapAttributionRecord]) -> Decimal | None:
    if not records:
        return None
    counts = Counter(item.historical_symbol for item in records)
    total = Decimal(len(records))
    return _quantize(
        sum(
            ((Decimal(value) / total) ** 2 for value in counts.values()),
            start=_ZERO,
        )
    )


def _distance(item: BreakoutDistributionDifference | None) -> Decimal:
    if item is None or item.total_variation_distance is None:
        return _ZERO
    return item.total_variation_distance


def _enum_counts(
    values: Sequence[BreakoutGapCause | None] | Any,
) -> tuple[tuple[str, int], ...]:
    counts = Counter(item.value for item in values if item is not None)
    return tuple(sorted(counts.items()))


def _reference_sort_key(
    record: BreakoutReferenceReconstructionRecord,
) -> tuple[date, str, str]:
    return (
        record.candidate_observation_date,
        record.historical_symbol,
        record.candidate_id,
    )


def _attribution_sort_key(
    record: BreakoutGapAttributionRecord,
) -> tuple[date, str, str]:
    return record.candidate_date, record.historical_symbol, record.candidate_id


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return _ZERO
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _decimal_float(value: float) -> Decimal:
    return _quantize(Decimal(str(value)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def _pct(value: Decimal) -> str:
    return f"{(value * _HUNDRED).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _optional(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _counts(values: Sequence[tuple[str, int]]) -> str:
    return "; ".join(f"{key}={value}" for key, value in values) or "none"


def _existing_source_recoverable(
    report: BreakoutRecoveryReadinessReport,
) -> int:
    return (
        report.recoverable_existing_source
        + report.recoverable_after_normalization_repair
        + report.recoverable_after_cutoff_resolution
    )


def _year_range(value: tuple[int | None, int | None]) -> str:
    return (
        "unavailable"
        if value[0] is None or value[1] is None
        else f"{value[0]} to {value[1]}"
    )


def _date_range(start: date | None, end: date | None) -> str:
    return f"{_date_text(start) or 'unavailable'} to {_date_text(end) or 'unavailable'}"


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _jsonable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, Decimal, StrEnum, Path)):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return cast(Any, str(value))


__all__ = [
    "BREAKOUT_GAP_AUDIT_VERSION",
    "SUPPORTED_GAP_GROUPINGS",
    "BreakoutAttributionConfidence",
    "BreakoutCandidateDiagnosticContext",
    "BreakoutDistributionDifference",
    "BreakoutGapAttributionRecord",
    "BreakoutGapAuditConclusion",
    "BreakoutGapCause",
    "BreakoutGapGroupRow",
    "BreakoutGapRecoveryClass",
    "BreakoutMissingnessMechanism",
    "BreakoutNumericDifference",
    "BreakoutOutcomeDifference",
    "BreakoutReadySampleBiasConclusion",
    "BreakoutRecoveryReadinessReport",
    "BreakoutRecoveryScenario",
    "BreakoutSelectionBiasReport",
    "BreakoutSourceCoverageMatrix",
    "BreakoutSourceGapAuditEngine",
    "BreakoutSourceGapAuditReport",
    "BreakoutSourcePathDisposition",
    "BreakoutSourceProbe",
    "export_breakout_gap_csv",
    "export_breakout_gap_json",
    "filter_breakout_gap_records",
    "group_breakout_gap_records",
    "parse_breakout_gap_cause",
    "parse_breakout_recovery_class",
    "render_breakout_gap_groups",
    "render_breakout_gap_sample",
    "render_breakout_recovery_readiness",
    "render_breakout_selection_bias",
    "render_breakout_source_coverage",
    "render_breakout_source_gap_audit",
]
