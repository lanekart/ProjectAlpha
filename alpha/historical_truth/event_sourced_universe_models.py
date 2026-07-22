"""Immutable contracts for HTR-009A2 event-sourced universe evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR009A2_CONTRACT_VERSION = "HTR-009A2-v1.0.0"
PRODUCTION_INFLUENCE = False


class SecurityEventType(StrEnum):
    LISTED = "LISTED"
    ADMITTED_TO_TRADING = "ADMITTED_TO_TRADING"
    RELISTED = "RELISTED"
    SYMBOL_CHANGED = "SYMBOL_CHANGED"
    NAME_CHANGED = "NAME_CHANGED"
    ISIN_CHANGED = "ISIN_CHANGED"
    SERIES_CHANGED = "SERIES_CHANGED"
    SUSPENDED = "SUSPENDED"
    SUSPENSION_REVOKED = "SUSPENSION_REVOKED"
    DELISTED = "DELISTED"
    ADMISSION_WITHDRAWN = "ADMISSION_WITHDRAWN"
    MERGED = "MERGED"
    DEMERGED = "DEMERGED"
    AMALGAMATED = "AMALGAMATED"
    SCHEME_EFFECTIVE = "SCHEME_EFFECTIVE"
    IDENTITY_TERMINATED = "IDENTITY_TERMINATED"
    SUCCESSOR_CREATED = "SUCCESSOR_CREATED"
    CHECKPOINT_PRESENT = "CHECKPOINT_PRESENT"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"


class MembershipEffect(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    UNCHANGED = "UNCHANGED"
    UNKNOWN = "UNKNOWN"


class TradabilityEffect(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    UNCHANGED = "UNCHANGED"
    UNKNOWN = "UNKNOWN"


class EventAdmissionState(StrEnum):
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    PROVISIONAL = "PROVISIONAL"
    CONFLICTING = "CONFLICTING"


class EventConfidenceState(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class EventSourceStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    INVENTORIED = "INVENTORIED"


class MembershipCertificationState(StrEnum):
    CERTIFIED_ACTIVE_TRADABLE = "CERTIFIED_ACTIVE_TRADABLE"
    CERTIFIED_ACTIVE_SUSPENDED = "CERTIFIED_ACTIVE_SUSPENDED"
    CERTIFIED_PRE_LISTING = "CERTIFIED_PRE_LISTING"
    CERTIFIED_POST_DELISTING = "CERTIFIED_POST_DELISTING"
    PROVISIONAL_ACTIVE = "PROVISIONAL_ACTIVE"
    UNRESOLVED_NO_LISTING_EVIDENCE = "UNRESOLVED_NO_LISTING_EVIDENCE"
    UNRESOLVED_NO_TERMINATION_EVIDENCE = "UNRESOLVED_NO_TERMINATION_EVIDENCE"
    UNRESOLVED_SUSPENSION_STATE = "UNRESOLVED_SUSPENSION_STATE"
    UNRESOLVED_IDENTITY_TRANSITION = "UNRESOLVED_IDENTITY_TRANSITION"
    SYMBOL_REUSE_CONFLICT = "SYMBOL_REUSE_CONFLICT"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    UNSUPPORTED_SECURITY_TYPE = "UNSUPPORTED_SECURITY_TYPE"


class EventSourcedCertificationState(StrEnum):
    EVENT_SOURCED_UNIVERSE_CERTIFIED = "EVENT_SOURCED_UNIVERSE_CERTIFIED"
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    BLOCKED_LISTING_EVIDENCE = "BLOCKED_LISTING_EVIDENCE"
    BLOCKED_TERMINATION_EVIDENCE = "BLOCKED_TERMINATION_EVIDENCE"
    BLOCKED_SUSPENSION_EVIDENCE = "BLOCKED_SUSPENSION_EVIDENCE"
    BLOCKED_IDENTITY_TRANSITIONS = "BLOCKED_IDENTITY_TRANSITIONS"
    BLOCKED_SYMBOL_REUSE = "BLOCKED_SYMBOL_REUSE"
    BLOCKED_CHECKPOINT_MISMATCH = "BLOCKED_CHECKPOINT_MISMATCH"
    BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE = "BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class IdentityRelationshipType(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    PREDECESSOR_SUCCESSOR = "PREDECESSOR_SUCCESSOR"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    AMALGAMATION = "AMALGAMATION"
    SCHEME = "SCHEME"
    SYMBOL_REUSE = "SYMBOL_REUSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EventSourceSpec:
    source_id: str
    source_family: str
    url: str
    parser: str
    event_type: SecurityEventType
    effective_date: date | None = None
    current_only: bool = False


@dataclass(frozen=True, slots=True)
class EventSourceInventoryRecord:
    source_id: str
    source_family: str
    source_url: str
    official_host: bool
    document_id: str | None
    retrieval_timestamp: str | None
    http_status: int | None
    content_type: str | None
    byte_size: int
    redirects: tuple[str, ...]
    sha256: str | None
    source_path: str | None
    parser: str
    records_inspected: int
    events_parsed: int
    events_admitted: int
    events_rejected: int
    status: EventSourceStatus
    failure_code: str | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class EventRejectionRecord:
    source_id: str
    source_url: str
    failure_code: str
    failure_detail: str
    row_number: int | None = None
    raw_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityEventRecord:
    event_id: str
    exchange: str
    event_type: SecurityEventType
    effective_date: date
    announcement_date: date | None
    old_symbol: str | None
    new_symbol: str | None
    old_series: str | None
    new_series: str | None
    old_isin: str | None
    new_isin: str | None
    security_name: str | None
    predecessor_identity: str | None
    successor_identity: str | None
    membership_effect: MembershipEffect
    tradability_effect: TradabilityEffect
    official_source_id: str
    document_location: str
    admission_state: EventAdmissionState
    confidence_state: EventConfidenceState

    @property
    def identity_key(self) -> str | None:
        isin = self.new_isin or self.old_isin
        return f"nse:isin:{isin}" if isin else None


@dataclass(frozen=True, slots=True)
class EventLineageRecord:
    event_id: str
    source_id: str
    source_sha256: str
    source_url: str
    parser: str
    row_number: int | None


@dataclass(frozen=True, slots=True)
class IdentityRelationshipRecord:
    relationship_id: str
    predecessor_identity: str
    successor_identity: str
    relationship_type: IdentityRelationshipType
    effective_date: date
    source_event_id: str
    confidence_state: EventConfidenceState


@dataclass(frozen=True, slots=True)
class SymbolIntervalRecord:
    identity_key: str
    symbol: str
    valid_from: date
    valid_to: date
    source_event_ids: tuple[str, ...]
    confidence_state: EventConfidenceState
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SeriesIntervalRecord:
    identity_key: str
    series: str
    valid_from: date
    valid_to: date
    source_event_ids: tuple[str, ...]
    confidence_state: EventConfidenceState
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NameIntervalRecord:
    identity_key: str
    security_name: str
    valid_from: date
    valid_to: date
    source_event_ids: tuple[str, ...]
    confidence_state: EventConfidenceState


@dataclass(frozen=True, slots=True)
class MembershipIntervalRecord:
    identity_key: str
    valid_from: date
    valid_to: date
    state: MembershipCertificationState
    source_event_ids: tuple[str, ...]
    identity_days: int
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradabilityIntervalRecord:
    identity_key: str
    valid_from: date
    valid_to: date
    tradable: bool
    state: MembershipCertificationState
    source_event_ids: tuple[str, ...]
    identity_days: int
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolReuseAssessment:
    symbol: str
    identity_keys: tuple[str, ...]
    isins: tuple[str, ...]
    names: tuple[str, ...]
    intervals: tuple[str, ...]
    overlap: bool
    interval_gap_days: int | None
    termination_evidence: bool
    successor_listing_evidence: bool
    candle_contamination: int
    candidate_contamination: int
    final_status: MembershipCertificationState


@dataclass(frozen=True, slots=True)
class SymbolChangeAssessment:
    old_symbol: str
    new_symbol: str
    effective_date: date | None
    old_identity: str
    new_identity: str
    classification: str
    source_event_ids: tuple[str, ...]
    final_status: MembershipCertificationState


@dataclass(frozen=True, slots=True)
class SuspensionAssessment:
    identity_key: str
    suspended_from: date
    restored_on: date | None
    source_event_ids: tuple[str, ...]
    final_status: MembershipCertificationState


@dataclass(frozen=True, slots=True)
class DelistingAssessment:
    identity_key: str
    effective_date: date
    event_type: SecurityEventType
    source_event_id: str
    confidence_state: EventConfidenceState


@dataclass(frozen=True, slots=True)
class CheckpointReconciliationRecord:
    checkpoint_date: date
    derived_identities: int
    master_identities: int
    missing_derived_identities: int
    unexpected_derived_identities: int
    symbol_mismatches: int
    isin_mismatches: int
    series_mismatches: int
    status_mismatches: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandleIntervalConflictRecord:
    trading_date: date
    last_trading_date: date
    symbol: str
    series: str
    isin: str | None
    identity_key: str
    membership_state: MembershipCertificationState
    reason_code: str
    candle_rows: int


@dataclass(frozen=True, slots=True)
class EventCandidateExposureRecord:
    membership_state: MembershipCertificationState
    affected_identities: int | None
    technical_candidates: int
    watchlist_candidates: int
    buy_candidates: int
    strong_buy_candidates: int
    approvals: int
    outcome_availability: str


@dataclass(frozen=True, slots=True)
class EventSummary:
    official_event_sources: int
    events_parsed: int
    events_admitted: int
    events_rejected: int
    counts_by_type: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class EventIdentitySummary:
    governed_identities: int
    provisional_identities: int
    unresolved_identities: int
    predecessor_successor_links: int
    symbol_reuse_resolved: int
    symbol_reuse_unresolved: int
    symbol_changes_resolved: int
    symbol_changes_unresolved: int
    interval_conflicts: int
    interval_gaps: int


@dataclass(frozen=True, slots=True)
class EventMembershipSummary:
    expected_identity_days: int
    certified_identity_days: int
    provisional_identity_days: int
    unresolved_identity_days: int
    active_tradable_days: int
    suspended_days: int
    pre_listing_days: int
    post_termination_days: int
    candle_rows_outside_certified_intervals: int


@dataclass(frozen=True, slots=True)
class YtdEvidenceSummary:
    year: int
    canonical_cutoff: date | None
    calendar_cutoff: date | None
    event_evidence_cutoff: date | None
    certified: bool
    blocker: str | None


@dataclass(frozen=True, slots=True)
class EventCertificationSummary:
    primary_state: EventSourcedCertificationState
    secondary_blockers: tuple[EventSourcedCertificationState, ...]
    rationale: str
    thresholds: tuple[str, ...]
    certified_start: date | None
    certified_end: date | None


@dataclass(frozen=True, slots=True)
class EventSourcedUniverseReport:
    contract_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    baseline: dict[str, Any]
    sources: tuple[EventSourceInventoryRecord, ...]
    rejected_evidence: tuple[EventRejectionRecord, ...]
    events: tuple[SecurityEventRecord, ...]
    event_lineage: tuple[EventLineageRecord, ...]
    identity_relationships: tuple[IdentityRelationshipRecord, ...]
    symbol_intervals: tuple[SymbolIntervalRecord, ...]
    series_intervals: tuple[SeriesIntervalRecord, ...]
    name_intervals: tuple[NameIntervalRecord, ...]
    membership_intervals: tuple[MembershipIntervalRecord, ...]
    tradability_intervals: tuple[TradabilityIntervalRecord, ...]
    symbol_reuse: tuple[SymbolReuseAssessment, ...]
    symbol_changes: tuple[SymbolChangeAssessment, ...]
    suspensions: tuple[SuspensionAssessment, ...]
    delistings: tuple[DelistingAssessment, ...]
    checkpoints: tuple[CheckpointReconciliationRecord, ...]
    candle_conflicts: tuple[CandleIntervalConflictRecord, ...]
    candidate_exposure: tuple[EventCandidateExposureRecord, ...]
    event_summary: EventSummary
    identity_summary: EventIdentitySummary
    membership_summary: EventMembershipSummary
    ytd_summary: YtdEvidenceSummary
    certification: EventCertificationSummary
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        raw = _jsonable(asdict(self))
        if not isinstance(raw, dict):
            raise TypeError("HTR-009A2 report must serialize to an object")
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


def stable_event_id(
    source_id: str,
    event_type: SecurityEventType,
    effective_date: date,
    *identity_fields: str | None,
) -> str:
    """Return a deterministic event ID without relying on source row order."""

    material = "|".join(
        (
            source_id,
            event_type.value,
            effective_date.isoformat(),
            *(str(value or "").strip().upper() for value in identity_fields),
        )
    )
    return f"nse-event:{sha256(material.encode()).hexdigest()}"


def identity_key(isin: str | None) -> str | None:
    normalized = str(isin or "").strip().upper()
    return f"nse:isin:{normalized}" if len(normalized) == 12 else None


def _jsonable(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "HTR009A2_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "CandleIntervalConflictRecord",
    "CheckpointReconciliationRecord",
    "DelistingAssessment",
    "EventAdmissionState",
    "EventCandidateExposureRecord",
    "EventCertificationSummary",
    "EventConfidenceState",
    "EventIdentitySummary",
    "EventLineageRecord",
    "EventMembershipSummary",
    "EventRejectionRecord",
    "EventSourceInventoryRecord",
    "EventSourceSpec",
    "EventSourceStatus",
    "EventSourcedCertificationState",
    "EventSourcedUniverseReport",
    "EventSummary",
    "IdentityRelationshipRecord",
    "IdentityRelationshipType",
    "MembershipCertificationState",
    "MembershipEffect",
    "MembershipIntervalRecord",
    "NameIntervalRecord",
    "SecurityEventRecord",
    "SecurityEventType",
    "SeriesIntervalRecord",
    "SuspensionAssessment",
    "SymbolChangeAssessment",
    "SymbolIntervalRecord",
    "SymbolReuseAssessment",
    "TradabilityEffect",
    "TradabilityIntervalRecord",
    "YtdEvidenceSummary",
    "identity_key",
    "stable_event_id",
]
