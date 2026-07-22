"""Immutable HTR-010A3 Tier A foundation-readiness contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010A3_CONTRACT_VERSION = "HTR-010A3-v1.0.0"
PRODUCTION_INFLUENCE = False


class ConflictType(StrEnum):
    DUPLICATE_INTERVAL = "DUPLICATE_INTERVAL"
    VALID_PARALLEL_SERIES = "VALID_PARALLEL_SERIES"
    SYMBOL_TRANSITION = "SYMBOL_TRANSITION"
    SERIES_TRANSITION = "SERIES_TRANSITION"
    DISTINCT_IDENTITIES_SHARED_SYMBOL = "DISTINCT_IDENTITIES_SHARED_SYMBOL"
    RELISTING = "RELISTING"
    MERGER_OR_AMALGAMATION = "MERGER_OR_AMALGAMATION"
    DEMERGER_OR_SCHEME = "DEMERGER_OR_SCHEME"
    ISIN_REPLACEMENT = "ISIN_REPLACEMENT"
    CURRENT_MASTER_BACKWARD_PROJECTION = "CURRENT_MASTER_BACKWARD_PROJECTION"
    PARSER_OR_INGESTION_DUPLICATION = "PARSER_OR_INGESTION_DUPLICATION"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    INSUFFICIENT_OFFICIAL_EVIDENCE = "INSUFFICIENT_OFFICIAL_EVIDENCE"


class ConflictOutcome(StrEnum):
    RESOLVED_SAME_IDENTITY = "RESOLVED_SAME_IDENTITY"
    RESOLVED_DISTINCT_IDENTITIES = "RESOLVED_DISTINCT_IDENTITIES"
    RESOLVED_PARALLEL_SERIES = "RESOLVED_PARALLEL_SERIES"
    RESOLVED_SYMBOL_TRANSITION = "RESOLVED_SYMBOL_TRANSITION"
    RESOLVED_SERIES_TRANSITION = "RESOLVED_SERIES_TRANSITION"
    RESOLVED_ISIN_TRANSITION = "RESOLVED_ISIN_TRANSITION"
    RESOLVED_PREDECESSOR_SUCCESSOR = "RESOLVED_PREDECESSOR_SUCCESSOR"
    RESOLVED_RELISTING = "RESOLVED_RELISTING"
    RESOLVED_BACKFILL_ERROR = "RESOLVED_BACKFILL_ERROR"
    QUARANTINED_IDENTITY_DATE_AMBIGUITY = "QUARANTINED_IDENTITY_DATE_AMBIGUITY"
    RETAINED_NON_BLOCKING_OFFICIAL_CONFLICT = "RETAINED_NON_BLOCKING_OFFICIAL_CONFLICT"
    UNRESOLVED_BLOCKING_CONFLICT = "UNRESOLVED_BLOCKING_CONFLICT"


class GapType(StrEnum):
    BOUNDED_SYMBOL_TRANSITION = "BOUNDED_SYMBOL_TRANSITION"
    BOUNDED_SERIES_TRANSITION = "BOUNDED_SERIES_TRANSITION"
    SUSPENSION_CANDIDATE = "SUSPENSION_CANDIDATE"
    RELISTING = "RELISTING"
    MERGER_OR_SCHEME_TRANSITION = "MERGER_OR_SCHEME_TRANSITION"
    MISSING_HISTORICAL_CHECKPOINT = "MISSING_HISTORICAL_CHECKPOINT"
    ARCHIVE_EVIDENCE_GAP = "ARCHIVE_EVIDENCE_GAP"
    ACTIVE_STATE_UNCERTAINTY = "ACTIVE_STATE_UNCERTAINTY"
    LEGITIMATE_NON_MEMBERSHIP = "LEGITIMATE_NON_MEMBERSHIP"
    UNRESOLVED = "UNRESOLVED"


class AmbiguityEffect(StrEnum):
    IDENTITY_AMBIGUITY = "IDENTITY_AMBIGUITY"
    MEMBERSHIP_AMBIGUITY_ONLY = "MEMBERSHIP_AMBIGUITY_ONLY"
    TRADABILITY_AMBIGUITY_ONLY = "TRADABILITY_AMBIGUITY_ONLY"
    NO_CORPORATE_ACTION_JOIN_AMBIGUITY = "NO_CORPORATE_ACTION_JOIN_AMBIGUITY"


class TerminationState(StrEnum):
    EXACT_TERMINATION = "EXACT_TERMINATION"
    BOUNDED_TERMINATION = "BOUNDED_TERMINATION"
    ACTIVE_AT_LATER_CHECKPOINT = "ACTIVE_AT_LATER_CHECKPOINT"
    SYMBOL_OR_SERIES_TRANSITION = "SYMBOL_OR_SERIES_TRANSITION"
    MERGER_OR_SCHEME_PREDECESSOR = "MERGER_OR_SCHEME_PREDECESSOR"
    OFFICIALLY_INACTIVE_DATE_UNAVAILABLE = "OFFICIALLY_INACTIVE_DATE_UNAVAILABLE"
    STALE_CURRENT_MASTER_BACKFILL = "STALE_CURRENT_MASTER_BACKFILL"
    CLASSIFICATION_CORRECTION = "CLASSIFICATION_CORRECTION"
    GENUINELY_UNRESOLVED_CESSATION = "GENUINELY_UNRESOLVED_CESSATION"


class SuspensionCeiling(StrEnum):
    HISTORICAL_SUSPENSION_CERTIFIED = "HISTORICAL_SUSPENSION_CERTIFIED"
    HISTORICAL_SUSPENSION_PARTIAL = "HISTORICAL_SUSPENSION_PARTIAL"
    CURRENT_ONLY_SUSPENSION_EVIDENCE = "CURRENT_ONLY_SUSPENSION_EVIDENCE"
    OFFICIAL_HISTORY_UNAVAILABLE = "OFFICIAL_HISTORY_UNAVAILABLE"
    CONFLICTING_SUSPENSION_EVIDENCE = "CONFLICTING_SUSPENSION_EVIDENCE"


class JoinReadiness(StrEnum):
    JOIN_READY_CERTIFIED = "JOIN_READY_CERTIFIED"
    JOIN_READY_BOUNDED_MEMBERSHIP = "JOIN_READY_BOUNDED_MEMBERSHIP"
    JOIN_READY_TRADABILITY_PARTIAL = "JOIN_READY_TRADABILITY_PARTIAL"
    QUARANTINED_IDENTITY_AMBIGUITY = "QUARANTINED_IDENTITY_AMBIGUITY"
    QUARANTINED_CONFLICTING_OFFICIAL_EVIDENCE = (
        "QUARANTINED_CONFLICTING_OFFICIAL_EVIDENCE"
    )
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"


class FoundationReadiness(StrEnum):
    READY_FOR_HTR_010B = "READY_FOR_HTR_010B"
    CONDITIONALLY_READY_FOR_HTR_010B = "CONDITIONALLY_READY_FOR_HTR_010B"
    NOT_READY_FOR_HTR_010B = "NOT_READY_FOR_HTR_010B"


@dataclass(frozen=True, slots=True)
class ConflictCase:
    case_id: str
    identity_ids: tuple[str, ...]
    symbols: tuple[str, ...]
    series: tuple[str, ...]
    isins: tuple[str, ...]
    security_names: tuple[str, ...]
    instrument_types: tuple[str, ...]
    overlap_start: date | None
    overlap_end: date | None
    listing_boundaries: tuple[str, ...]
    termination_boundaries: tuple[str, ...]
    checkpoint_observations: tuple[str, ...]
    transition_event_ids: tuple[str, ...]
    corporate_action_ids: tuple[str, ...]
    candle_observation: str
    official_source_ids: tuple[str, ...]
    conflict_type: ConflictType
    proposed_resolution: ConflictOutcome
    confidence: str
    unresolved_evidence_requirement: str | None


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    case_id: str
    identity_key: str
    outcome: ConflictOutcome
    blocking: bool
    identity_date_assignment_unique: bool
    excluded_from_certified_join: bool
    authority_level: int
    rationale: str


@dataclass(frozen=True, slots=True)
class GapResolution:
    gap_id: str
    identity_key: str
    gap_type: GapType
    earliest_possible_effective_date: date
    latest_possible_effective_date: date
    last_certified_prior_state: str
    first_certified_subsequent_state: str
    effect: AmbiguityEffect
    corporate_action_join_valid: bool
    confidence: str
    rationale: str


@dataclass(frozen=True, slots=True)
class DiscrepancyResolution:
    symbol: str
    identity_key: str
    checkpoint_date: date
    event_date: date | None
    derived_state: str
    official_state: str
    cause: str
    final_state: str
    checkpoint_treatment: str
    join_readiness: JoinReadiness
    parity_should_hold: bool
    source_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminationBoundary:
    identity_key: str
    symbol: str
    state: TerminationState
    exact_date: date | None
    lower_bound: date | None
    upper_bound: date | None
    affects_corporate_action_join: bool
    evidence_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class SuspensionEvidenceBoundary:
    state: SuspensionCeiling
    official_source_families: tuple[str, ...]
    acquired_sources: int
    failed_sources: int
    reconstructed_events: int
    permanent_known_limitation: bool
    membership_blocking: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class DailyActivityContract:
    source_family: str
    years_covered: str
    file_format: str
    inclusion_semantics: str
    zero_volume_rows: int
    suspended_security_behavior: str
    row_absence_proves: str
    confidence: str
    membership_inference_allowed: bool
    suspension_inference_allowed: bool
    termination_inference_allowed: bool
    trading_activity_evidence_allowed: bool
    candle_computation_allowed: bool
    expected_row_completeness_audit_allowed: bool


@dataclass(frozen=True, slots=True)
class CorporateActionJoinReadiness:
    identity_key: str
    symbol: str
    isin: str | None
    state: JoinReadiness
    unique_identity: bool
    bounded_membership: bool
    tradability_partial: bool
    quarantine_reason: str | None
    admitted_to_certified_join: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class ReadinessDecision:
    state: FoundationReadiness
    blockers: tuple[str, ...]
    quarantined_identities: int
    admitted_identities: int
    denominator_identities: int
    quarantine_policy: str
    recommended_next_milestone: str
    rationale: str


@dataclass(frozen=True, slots=True)
class FoundationReadinessReport:
    contract_version: str
    production_influence: bool
    start_date: date
    end_date: date
    conflict_cases: tuple[ConflictCase, ...]
    conflict_evidence: tuple[dict[str, Any], ...]
    conflict_resolutions: tuple[ConflictResolution, ...]
    gap_resolutions: tuple[GapResolution, ...]
    discrepancies_2026: tuple[DiscrepancyResolution, ...]
    termination_boundaries: tuple[TerminationBoundary, ...]
    suspension_ceiling: tuple[SuspensionEvidenceBoundary, ...]
    daily_source_contracts: tuple[DailyActivityContract, ...]
    join_readiness: tuple[CorporateActionJoinReadiness, ...]
    quarantined_identities: tuple[CorporateActionJoinReadiness, ...]
    readiness: ReadinessDecision
    rejected_evidence: tuple[dict[str, Any], ...]
    source_checksums: tuple[tuple[str, str], ...]
    canonical_candle_fingerprint: str
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = _jsonable(asdict(self))
        if not isinstance(payload, dict):
            raise TypeError("HTR-010A3 report must serialize to an object")
        if not include_hash:
            payload["report_sha256"] = ""
        return payload

    def calculated_sha256(self) -> str:
        encoded = json.dumps(
            self.payload(include_hash=False), sort_keys=True, separators=(",", ":")
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
