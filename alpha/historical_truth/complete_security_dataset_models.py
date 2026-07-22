"""Immutable contracts for HTR-010A complete security certification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010A_CONTRACT_VERSION = "HTR-010A-v1.0.0"
PRODUCTION_INFLUENCE = False


class IdentityState(StrEnum):
    GOVERNED_IDENTITY = "GOVERNED_IDENTITY"
    PROVISIONAL_IDENTITY = "PROVISIONAL_IDENTITY"
    MISSING_IDENTITY_EVIDENCE = "MISSING_IDENTITY_EVIDENCE"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    INVALID_ISIN = "INVALID_ISIN"
    ISIN_CONFLICT = "ISIN_CONFLICT"
    SYMBOL_REUSE_RESOLVED = "SYMBOL_REUSE_RESOLVED"
    SYMBOL_REUSE_UNRESOLVED = "SYMBOL_REUSE_UNRESOLVED"
    SYMBOL_CHANGE_RESOLVED = "SYMBOL_CHANGE_RESOLVED"
    SYMBOL_CHANGE_UNRESOLVED = "SYMBOL_CHANGE_UNRESOLVED"
    SERIES_TRANSITION_RESOLVED = "SERIES_TRANSITION_RESOLVED"
    SERIES_TRANSITION_UNRESOLVED = "SERIES_TRANSITION_UNRESOLVED"
    PREDECESSOR_SUCCESSOR_RESOLVED = "PREDECESSOR_SUCCESSOR_RESOLVED"
    PREDECESSOR_SUCCESSOR_UNRESOLVED = "PREDECESSOR_SUCCESSOR_UNRESOLVED"
    OVERLAPPING_IDENTITY_INTERVALS = "OVERLAPPING_IDENTITY_INTERVALS"
    IDENTITY_INTERVAL_GAP = "IDENTITY_INTERVAL_GAP"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    UNSUPPORTED_SECURITY_TYPE = "UNSUPPORTED_SECURITY_TYPE"


class MembershipState(StrEnum):
    CERTIFIED_ACTIVE_TRADABLE = "CERTIFIED_ACTIVE_TRADABLE"
    CERTIFIED_ACTIVE_SUSPENDED = "CERTIFIED_ACTIVE_SUSPENDED"
    CERTIFIED_PRE_LISTING = "CERTIFIED_PRE_LISTING"
    CERTIFIED_POST_TERMINATION = "CERTIFIED_POST_TERMINATION"
    CERTIFIED_RELISTED = "CERTIFIED_RELISTED"
    PROVISIONAL_ACTIVE = "PROVISIONAL_ACTIVE"
    UNRESOLVED_NO_LISTING_EVIDENCE = "UNRESOLVED_NO_LISTING_EVIDENCE"
    UNRESOLVED_NO_TERMINATION_EVIDENCE = "UNRESOLVED_NO_TERMINATION_EVIDENCE"
    UNRESOLVED_SUSPENSION_STATE = "UNRESOLVED_SUSPENSION_STATE"
    UNRESOLVED_IDENTITY_TRANSITION = "UNRESOLVED_IDENTITY_TRANSITION"
    SYMBOL_REUSE_CONFLICT = "SYMBOL_REUSE_CONFLICT"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    UNSUPPORTED_SECURITY_TYPE = "UNSUPPORTED_SECURITY_TYPE"


class CandleReconciliationState(StrEnum):
    CERTIFIED_IN_INTERVAL = "CERTIFIED_IN_INTERVAL"
    PROVISIONAL_IN_INTERVAL = "PROVISIONAL_IN_INTERVAL"
    PRE_LISTING_ROW = "PRE_LISTING_ROW"
    POST_TERMINATION_ROW = "POST_TERMINATION_ROW"
    SUSPENDED_DATE_ROW = "SUSPENDED_DATE_ROW"
    SYMBOL_INTERVAL_MISMATCH = "SYMBOL_INTERVAL_MISMATCH"
    SERIES_INTERVAL_MISMATCH = "SERIES_INTERVAL_MISMATCH"
    ISIN_MISMATCH = "ISIN_MISMATCH"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNSUPPORTED_SERIES = "UNSUPPORTED_SERIES"


class SourceStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    INVENTORIED = "INVENTORIED"


class CertificationTier(StrEnum):
    TIER_A_CERTIFIED = "TIER_A_CERTIFIED"
    TIER_A_PARTIAL = "TIER_A_PARTIAL"
    IDENTITY_CERTIFIED_MEMBERSHIP_PARTIAL = "IDENTITY_CERTIFIED_MEMBERSHIP_PARTIAL"
    IDENTITY_PARTIAL = "IDENTITY_PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTING = "CONFLICTING"


class OverallCertificationState(StrEnum):
    FULL_MARKET_IDENTITY_MEMBERSHIP_CERTIFIED = (
        "FULL_MARKET_IDENTITY_MEMBERSHIP_CERTIFIED"
    )
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    BLOCKED_LISTING_EVIDENCE = "BLOCKED_LISTING_EVIDENCE"
    BLOCKED_TERMINATION_EVIDENCE = "BLOCKED_TERMINATION_EVIDENCE"
    BLOCKED_SUSPENSION_EVIDENCE = "BLOCKED_SUSPENSION_EVIDENCE"
    BLOCKED_SYMBOL_REUSE = "BLOCKED_SYMBOL_REUSE"
    BLOCKED_IDENTITY_TRANSITIONS = "BLOCKED_IDENTITY_TRANSITIONS"
    BLOCKED_CANDLE_RECONCILIATION = "BLOCKED_CANDLE_RECONCILIATION"
    BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE = "BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class SourceInventoryRecord:
    source_id: str
    source_family: str
    source_url: str
    source_path: str | None
    official_host: bool
    retrieval_timestamp: str | None
    http_status: int | None
    content_type: str | None
    redirects: tuple[str, ...]
    byte_size: int
    sha256: str | None
    parser: str
    records_parsed: int
    records_admitted: int
    records_rejected: int
    status: SourceStatus
    failure_code: str | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class RejectedEvidenceRecord:
    source_id: str
    failure_code: str
    failure_detail: str
    raw_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityCensusRecord:
    exchange: str
    symbol: str
    series: str
    isin: str | None
    security_name: str | None
    first_observed: date | None
    last_observed: date | None
    candle_rows: int
    source_ids: tuple[str, ...]
    source_record_count: int
    supported_security_type: bool
    identity_key: str


@dataclass(frozen=True, slots=True)
class CompleteSecurityIdentity:
    identity_key: str
    exchange: str
    isin: str | None
    current_symbol: str | None
    current_series: str | None
    current_name: str | None
    first_evidence_date: date | None
    last_evidence_date: date | None
    identity_state: IdentityState
    secondary_issue_codes: tuple[str, ...]
    official_source_ids: tuple[str, ...]
    synthetic_reason: str | None
    candidate_independent: bool = True


@dataclass(frozen=True, slots=True)
class IdentityInterval:
    identity_key: str
    valid_from: date
    valid_to: date
    identity_state: IdentityState
    source_event_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttributeInterval:
    identity_key: str
    value: str
    valid_from: date
    valid_to: date
    confidence_state: str
    source_event_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompleteMembershipInterval:
    identity_key: str
    valid_from: date
    valid_to: date
    state: MembershipState
    tradable: bool
    source_event_ids: tuple[str, ...]
    identity_days: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuspensionInterval:
    identity_key: str
    valid_from: date
    valid_to: date | None
    restoration_date: date | None
    source_event_ids: tuple[str, ...]
    state: str


@dataclass(frozen=True, slots=True)
class TerminationRecord:
    identity_key: str
    termination_date: date
    event_type: str
    source_event_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    transition_id: str
    transition_type: str
    effective_date: date
    predecessor_identity: str | None
    successor_identity: str | None
    old_symbol: str | None
    new_symbol: str | None
    old_series: str | None
    new_series: str | None
    old_isin: str | None
    new_isin: str | None
    source_event_id: str
    final_state: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolReuseRecord:
    symbol: str
    identity_keys: tuple[str, ...]
    isins: tuple[str, ...]
    first_date: date | None
    last_date: date | None
    interval_overlap: bool
    interval_gap: bool
    final_state: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandleReconciliationSummary:
    identity_key: str
    state: CandleReconciliationState
    row_count: int
    first_date: date
    last_date: date


@dataclass(frozen=True, slots=True)
class SecuritySessionGapSummary:
    identity_key: str
    classification: str
    gap_count: int
    first_date: date | None
    last_date: date | None


@dataclass(frozen=True, slots=True)
class DatasetCertificationRecord:
    identity_key: str
    identity_coverage: str
    listing_coverage: str
    termination_coverage: str
    suspension_coverage: str
    symbol_history_coverage: str
    series_history_coverage: str
    isin_history_coverage: str
    membership_coverage: str
    tradability_coverage: str
    candle_reconciliation: str
    source_lineage_coverage: str
    corporate_transition_coverage: str
    overall_state: CertificationTier
    unresolved_blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    raw_symbols: int
    symbol_series_pairs: int
    isins: int
    governed_identities: int
    provisional_identities: int
    unresolved_identities: int
    unsupported_security_types: int


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    source_families_attempted: int
    sources_attempted: int
    sources_acquired: int
    sources_reused: int
    sources_failed: int
    records_parsed: int
    records_admitted: int
    records_rejected: int


@dataclass(frozen=True, slots=True)
class MembershipSummary:
    membership_intervals: int
    tradability_intervals: int
    listing_boundaries: int
    termination_boundaries: int
    suspension_intervals: int
    restoration_events: int
    relisting_intervals: int
    expected_identity_days: int
    certified_identity_days: int
    provisional_identity_days: int
    unresolved_identity_days: int


@dataclass(frozen=True, slots=True)
class CandleSummary:
    total_rows: int
    certified_rows: int
    provisional_rows: int
    pre_listing_rows: int
    post_termination_rows: int
    suspended_rows: int
    symbol_mismatches: int
    series_mismatches: int
    isin_mismatches: int
    unresolved_rows: int
    unsupported_series_rows: int


@dataclass(frozen=True, slots=True)
class ContinuitySummary:
    expected_security_sessions: int
    observed_security_sessions: int
    explained_missing_sessions: int
    unexplained_missing_sessions: int
    identities_with_zero_unexplained_gaps: int
    identities_with_unresolved_gaps: int


@dataclass(frozen=True, slots=True)
class YtdSummary:
    year: int
    calendar_state: str
    calendar_cutoff: date | None
    canonical_cutoff: date | None
    identity_evidence_cutoff: date | None
    final_common_date: date | None
    universe_size: int
    governed_identities: int
    membership_intervals: int
    unresolved_identities: int
    final_state: str
    blocker: str | None


@dataclass(frozen=True, slots=True)
class CertificationSummary:
    primary_state: OverallCertificationState
    secondary_blockers: tuple[OverallCertificationState, ...]
    tier_a_thresholds: tuple[str, ...]
    tier_a_count: int
    tier_a_coverage: float
    rationale: str


@dataclass(frozen=True, slots=True)
class CompleteSecurityDatasetReport:
    contract_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    source_inventory: tuple[SourceInventoryRecord, ...]
    rejected_evidence: tuple[RejectedEvidenceRecord, ...]
    census: tuple[SecurityCensusRecord, ...]
    identities: tuple[CompleteSecurityIdentity, ...]
    identity_intervals: tuple[IdentityInterval, ...]
    symbol_intervals: tuple[AttributeInterval, ...]
    series_intervals: tuple[AttributeInterval, ...]
    membership_intervals: tuple[CompleteMembershipInterval, ...]
    tradability_intervals: tuple[CompleteMembershipInterval, ...]
    suspensions: tuple[SuspensionInterval, ...]
    terminations: tuple[TerminationRecord, ...]
    symbol_reuse: tuple[SymbolReuseRecord, ...]
    transitions: tuple[TransitionRecord, ...]
    candle_reconciliation: tuple[CandleReconciliationSummary, ...]
    security_session_gaps: tuple[SecuritySessionGapSummary, ...]
    certification_matrix: tuple[DatasetCertificationRecord, ...]
    population_summary: PopulationSummary
    evidence_summary: EvidenceSummary
    membership_summary: MembershipSummary
    candle_summary: CandleSummary
    continuity_summary: ContinuitySummary
    ytd_summary: YtdSummary
    certification: CertificationSummary
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        raw = _jsonable(asdict(self))
        if not isinstance(raw, dict):
            raise TypeError("HTR-010A report must serialize to an object")
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


def stable_synthetic_identity(
    exchange: str,
    symbol: str,
    series: str,
    first_date: date | None,
    last_date: date | None,
) -> str:
    material = "|".join(
        (
            exchange.upper(),
            symbol.upper(),
            series.upper(),
            first_date.isoformat() if first_date else "UNKNOWN",
            last_date.isoformat() if last_date else "UNKNOWN",
        )
    )
    return f"nse:synthetic:{sha256(material.encode()).hexdigest()}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, StrEnum)):
        return value.isoformat() if isinstance(value, date) else value.value
    return value


__all__ = [
    "AttributeInterval",
    "CandleReconciliationState",
    "CandleReconciliationSummary",
    "CandleSummary",
    "CertificationSummary",
    "CertificationTier",
    "CompleteMembershipInterval",
    "CompleteSecurityDatasetReport",
    "CompleteSecurityIdentity",
    "ContinuitySummary",
    "DatasetCertificationRecord",
    "EvidenceSummary",
    "HTR010A_CONTRACT_VERSION",
    "IdentityInterval",
    "IdentityState",
    "MembershipState",
    "MembershipSummary",
    "OverallCertificationState",
    "PRODUCTION_INFLUENCE",
    "PopulationSummary",
    "RejectedEvidenceRecord",
    "SecurityCensusRecord",
    "SecuritySessionGapSummary",
    "SourceInventoryRecord",
    "SourceStatus",
    "SuspensionInterval",
    "SymbolReuseRecord",
    "TerminationRecord",
    "TransitionRecord",
    "YtdSummary",
    "stable_synthetic_identity",
]
