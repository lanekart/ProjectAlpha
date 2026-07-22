"""Immutable HTR-010A2 lifecycle and session-semantics contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010A2_CONTRACT_VERSION = "HTR-010A2-v1.0.0"
LIFECYCLE_VERSION = "NSE-CM-LIFECYCLE-v1.0.0"
PRODUCTION_INFLUENCE = False


class PrimaryCertificationState(StrEnum):
    TIER_A_LIFECYCLE_CERTIFIED = "TIER_A_LIFECYCLE_CERTIFIED"
    TIER_A_MEMBERSHIP_CERTIFIED_TRADABILITY_PARTIAL = (
        "TIER_A_MEMBERSHIP_CERTIFIED_TRADABILITY_PARTIAL"
    )
    TIER_A_MEMBERSHIP_PARTIAL = "TIER_A_MEMBERSHIP_PARTIAL"
    TIER_A_INTERVAL_CONFLICT = "TIER_A_INTERVAL_CONFLICT"
    SUPPORTED_NON_CORE_CERTIFIED = "SUPPORTED_NON_CORE_CERTIFIED"
    SUPPORTED_NON_CORE_PARTIAL = "SUPPORTED_NON_CORE_PARTIAL"
    SEPARATE_ASSET_CLASS = "SEPARATE_ASSET_CLASS"
    PRESERVED_UNSUPPORTED = "PRESERVED_UNSUPPORTED"
    UNKNOWN_CLASSIFICATION = "UNKNOWN_CLASSIFICATION"
    CONFLICTING_CLASSIFICATION = "CONFLICTING_CLASSIFICATION"
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"


class CertificationIssue(StrEnum):
    MISSING_TERMINATION_EVIDENCE = "MISSING_TERMINATION_EVIDENCE"
    MISSING_SUSPENSION_EVIDENCE = "MISSING_SUSPENSION_EVIDENCE"
    INTERVAL_OVERLAP = "INTERVAL_OVERLAP"
    INTERVAL_GAP = "INTERVAL_GAP"
    PROVISIONAL_LISTING_BOUNDARY = "PROVISIONAL_LISTING_BOUNDARY"
    SYMBOL_REUSE = "SYMBOL_REUSE"
    SERIES_CONFLICT = "SERIES_CONFLICT"
    ISIN_CONFLICT = "ISIN_CONFLICT"
    PREDECESSOR_SUCCESSOR_UNRESOLVED = "PREDECESSOR_SUCCESSOR_UNRESOLVED"
    CHECKPOINT_MISMATCH = "CHECKPOINT_MISMATCH"
    CANDLE_CONTINUITY_ANOMALY = "CANDLE_CONTINUITY_ANOMALY"


class DuplicateClassification(StrEnum):
    IDENTICAL_DUPLICATE_OBSERVATION = "IDENTICAL_DUPLICATE_OBSERVATION"
    REPEATED_CHECKPOINT_OBSERVATION = "REPEATED_CHECKPOINT_OBSERVATION"
    LEGITIMATE_EFFECTIVE_DATED_OBSERVATION = "LEGITIMATE_EFFECTIVE_DATED_OBSERVATION"
    MULTIPLE_OFFICIAL_SOURCES_SAME_FACT = "MULTIPLE_OFFICIAL_SOURCES_SAME_FACT"
    CONFLICTING_OFFICIAL_OBSERVATION = "CONFLICTING_OFFICIAL_OBSERVATION"
    PARSER_DUPLICATION = "PARSER_DUPLICATION"
    INGESTION_DUPLICATION = "INGESTION_DUPLICATION"
    SYNTHETIC_DUPLICATION = "SYNTHETIC_DUPLICATION"
    UNRESOLVED = "UNRESOLVED"


class IntervalType(StrEnum):
    IDENTITY_VALIDITY = "IDENTITY_VALIDITY"
    SYMBOL = "SYMBOL"
    SERIES = "SERIES"
    ISIN = "ISIN"
    MARKET_MEMBERSHIP = "MARKET_MEMBERSHIP"
    TRADABILITY = "TRADABILITY"
    SUSPENSION = "SUSPENSION"
    TERMINATION = "TERMINATION"
    RELISTING = "RELISTING"
    PREDECESSOR_SUCCESSOR = "PREDECESSOR_SUCCESSOR"


class LifecycleRepairType(StrEnum):
    UNCHANGED = "UNCHANGED"
    COLLAPSED_IDENTICAL = "COLLAPSED_IDENTICAL"
    MERGED_ADJACENT = "MERGED_ADJACENT"
    RETAINED_PARALLEL = "RETAINED_PARALLEL"
    REMOVED_CHECKPOINT_BACKFILL = "REMOVED_CHECKPOINT_BACKFILL"
    RETAINED_CONFLICT = "RETAINED_CONFLICT"
    BOUNDED_UNCERTAIN = "BOUNDED_UNCERTAIN"


class OverlapFinalState(StrEnum):
    RESOLVED_DUPLICATE = "RESOLVED_DUPLICATE"
    RESOLVED_PARALLEL_SERIES = "RESOLVED_PARALLEL_SERIES"
    RESOLVED_SYMBOL_TRANSITION = "RESOLVED_SYMBOL_TRANSITION"
    RESOLVED_SERIES_TRANSITION = "RESOLVED_SERIES_TRANSITION"
    RESOLVED_PREDECESSOR_SUCCESSOR = "RESOLVED_PREDECESSOR_SUCCESSOR"
    RESOLVED_RELISTING = "RESOLVED_RELISTING"
    RESOLVED_CHECKPOINT_BACKFILL = "RESOLVED_CHECKPOINT_BACKFILL"
    RETAINED_OFFICIAL_CONFLICT = "RETAINED_OFFICIAL_CONFLICT"
    UNRESOLVED_INSUFFICIENT_EVIDENCE = "UNRESOLVED_INSUFFICIENT_EVIDENCE"


class GapFinalState(StrEnum):
    NO_OFFICIAL_STATE_OBSERVATION = "NO_OFFICIAL_STATE_OBSERVATION"
    SYMBOL_TRANSITION = "SYMBOL_TRANSITION"
    SERIES_TRANSITION = "SERIES_TRANSITION"
    SUSPENSION = "SUSPENSION"
    TEMPORARY_TRADING_CESSATION = "TEMPORARY_TRADING_CESSATION"
    RELISTING = "RELISTING"
    PREDECESSOR_SUCCESSOR_TRANSITION = "PREDECESSOR_SUCCESSOR_TRANSITION"
    CHECKPOINT_GAP = "CHECKPOINT_GAP"
    ARCHIVE_GAP = "ARCHIVE_GAP"
    PARSER_GAP = "PARSER_GAP"
    LEGITIMATE_MARKET_ABSENCE = "LEGITIMATE_MARKET_ABSENCE"
    UNRESOLVED = "UNRESOLVED"


class SourceSemanticsState(StrEnum):
    ALL_LISTED_SECURITIES_EXPECTED = "ALL_LISTED_SECURITIES_EXPECTED"
    ALL_TRADABLE_SECURITIES_EXPECTED = "ALL_TRADABLE_SECURITIES_EXPECTED"
    TRADED_SECURITIES_ONLY = "TRADED_SECURITIES_ONLY"
    REPORTABLE_ACTIVITY_ONLY = "REPORTABLE_ACTIVITY_ONLY"
    FORMAT_DEPENDENT = "FORMAT_DEPENDENT"
    SEMANTICS_UNRESOLVED = "SEMANTICS_UNRESOLVED"


class AbsenceReason(StrEnum):
    ROW_NOT_EXPECTED_SOURCE_SEMANTICS = "ROW_NOT_EXPECTED_SOURCE_SEMANTICS"
    NO_REPORTED_TRADING_ACTIVITY = "NO_REPORTED_TRADING_ACTIVITY"
    CERTIFIED_SUSPENSION = "CERTIFIED_SUSPENSION"
    PROVISIONAL_SUSPENSION = "PROVISIONAL_SUSPENSION"
    PRE_LISTING = "PRE_LISTING"
    POST_TERMINATION = "POST_TERMINATION"
    SERIES_NOT_ACTIVE = "SERIES_NOT_ACTIVE"
    IDENTITY_TRANSITION_GAP = "IDENTITY_TRANSITION_GAP"
    OFFICIAL_ARCHIVE_UNAVAILABLE = "OFFICIAL_ARCHIVE_UNAVAILABLE"
    SOURCE_FILE_INVALID = "SOURCE_FILE_INVALID"
    ROW_REJECTED_VALIDATION = "ROW_REJECTED_VALIDATION"
    IDENTITY_RESOLUTION_FAILURE = "IDENTITY_RESOLUTION_FAILURE"
    OFFICIAL_ROW_EXPECTED_BUT_MISSING = "OFFICIAL_ROW_EXPECTED_BUT_MISSING"
    UNRESOLVED_SOURCE_SEMANTICS = "UNRESOLVED_SOURCE_SEMANTICS"
    UNEXPLAINED = "UNEXPLAINED"


class ReadinessState(StrEnum):
    READY_FOR_HTR_010B = "READY_FOR_HTR_010B"
    CONDITIONALLY_READY_FOR_HTR_010B = "CONDITIONALLY_READY_FOR_HTR_010B"
    NOT_READY_FOR_HTR_010B = "NOT_READY_FOR_HTR_010B"


@dataclass(frozen=True, slots=True)
class PrimaryCertification:
    identity_key: str
    support_state: str
    instrument_type: str
    primary_state: PrimaryCertificationState
    issue_flags: tuple[CertificationIssue, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class CertificationReconciliation:
    population: str
    primary_state: PrimaryCertificationState
    identities: int
    expected_population: int
    reconciliation_equation: str


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    canonical_observation_id: str
    duplicate_group_id: str
    identity_key: str
    symbol: str
    series: str
    isin: str | None
    security_name: str | None
    effective_from: date
    effective_to: date
    source_precedence: int
    conflict_state: str
    supporting_record_ids: tuple[str, ...]
    selected_fact: str


@dataclass(frozen=True, slots=True)
class DuplicateSourceRecord:
    source_record_id: str
    canonical_observation_id: str
    duplicate_group_id: str
    identity_key: str
    symbol: str
    series: str
    classification: DuplicateClassification
    effective_date: date
    source_ids: tuple[str, ...]
    conflict_state: str
    reason: str


@dataclass(frozen=True, slots=True)
class CanonicalLifecycleInterval:
    canonical_interval_id: str
    identity_key: str
    interval_type: IntervalType
    value: str
    valid_from: date
    valid_to: date
    original_interval_ids: tuple[str, ...]
    repair_type: LifecycleRepairType
    repair_reason: str
    source_evidence: tuple[str, ...]
    confidence_state: str
    reconstruction_version: str
    contradictory: bool


@dataclass(frozen=True, slots=True)
class LifecycleRepair:
    repair_id: str
    identity_key: str
    interval_type: IntervalType
    before_values: tuple[str, ...]
    after_value: str
    repair_type: LifecycleRepairType
    reason: str
    source_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RemainingOverlap:
    conflict_id: str
    identity_key: str
    support_state: str
    same_isin: bool
    same_instrument_type: bool
    same_series: bool
    within_one_identity: bool
    checkpoint_dates: tuple[date, ...]
    transition_event_ids: tuple[str, ...]
    final_state: OverlapFinalState
    ambiguous_identity_date_assignment: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RemainingGap:
    gap_id: str
    identity_key: str
    support_state: str
    known_active_on_or_before: date | None
    known_inactive_on_or_after: date | None
    earliest_possible_effective_date: date
    latest_possible_effective_date: date
    exact_date_available: bool
    final_state: GapFinalState
    evidence_source_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class BoundaryRange:
    identity_key: str
    support_state: str
    exact_listing_date: date | None
    listing_lower_bound: date | None
    listing_upper_bound: date | None
    first_official_checkpoint: date | None
    first_canonical_candle: date | None
    exact_termination_date: date | None
    termination_lower_bound: date | None
    termination_upper_bound: date | None
    final_official_active_checkpoint: date | None
    final_canonical_candle: date | None
    current_active: bool | None
    confidence: str
    missing_historical_termination: bool


@dataclass(frozen=True, slots=True)
class DailySourceSemantics:
    source_family: str
    format_name: str
    covered_from: date
    covered_to: date
    inclusion_contract: SourceSemanticsState
    zero_volume_rows: int
    total_rows: int
    suspended_security_behavior: str
    official_documentation_state: str
    confidence: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionExpectationSummary:
    support_state: str
    membership_sessions: int
    tradability_sessions: int
    expected_source_rows: int
    observed_source_rows: int
    trading_activity_sessions: int
    candle_computable_sessions: int
    confidence: str


@dataclass(frozen=True, slots=True)
class MissingSessionReclassification:
    support_state: str
    absence_reason: AbsenceReason
    sessions: int
    counted_as_true_source_gap: bool
    counted_as_candle_computability_gap: bool
    confidence: str
    rationale: str


@dataclass(frozen=True, slots=True)
class CheckpointDifference:
    identity_key: str
    symbol: str
    series: str
    isin: str | None
    derived_interval_state: str
    checkpoint_state: str
    source_evidence: tuple[str, ...]
    classification: str
    explained: bool


@dataclass(frozen=True, slots=True)
class ReadinessDecision:
    state: ReadinessState
    blockers: tuple[str, ...]
    satisfied_requirements: tuple[str, ...]
    recommended_next_milestone: str
    rationale: str


@dataclass(frozen=True, slots=True)
class LifecycleSessionReport:
    contract_version: str
    lifecycle_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    primary_certifications: tuple[PrimaryCertification, ...]
    certification_reconciliation: tuple[CertificationReconciliation, ...]
    duplicate_source_records: tuple[DuplicateSourceRecord, ...]
    canonical_observations: tuple[CanonicalObservation, ...]
    lifecycle_intervals: tuple[CanonicalLifecycleInterval, ...]
    interval_repairs: tuple[LifecycleRepair, ...]
    remaining_overlaps: tuple[RemainingOverlap, ...]
    remaining_gaps: tuple[RemainingGap, ...]
    boundary_ranges: tuple[BoundaryRange, ...]
    suspension_source_inventory: tuple[dict[str, Any], ...]
    suspension_events: tuple[dict[str, Any], ...]
    daily_source_semantics: tuple[DailySourceSemantics, ...]
    session_expectations: tuple[SessionExpectationSummary, ...]
    missing_session_reclassification: tuple[MissingSessionReclassification, ...]
    checkpoint_reconciliation_2026: tuple[CheckpointDifference, ...]
    readiness: ReadinessDecision
    rejected_evidence: tuple[dict[str, Any], ...]
    source_checksums: tuple[tuple[str, str], ...]
    canonical_candle_fingerprint: str
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        raw = _jsonable(asdict(self))
        if not isinstance(raw, dict):
            raise TypeError("HTR-010A2 report must serialize to an object")
        if not include_hash:
            raw["report_sha256"] = ""
        return raw

    def calculated_sha256(self) -> str:
        encoded = json.dumps(
            self.payload(include_hash=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return sha256(encoded).hexdigest()


def stable_id(prefix: str, *values: object) -> str:
    material = "|".join(str(value or "").upper() for value in values)
    return f"{prefix}:{sha256(material.encode()).hexdigest()}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


__all__ = [name for name in globals() if not name.startswith("_")]
