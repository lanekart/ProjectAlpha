"""Typed domain contracts for HTR-009A point-in-time identity certification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR009A_CONTRACT_VERSION = "HTR-009A-v1.0.0"
PRODUCTION_INFLUENCE = False
SUPPORTED_SERIES = frozenset({"EQ"})


class IdentityState(StrEnum):
    GOVERNED_IDENTITY = "GOVERNED_IDENTITY"
    PROVISIONAL_IDENTITY = "PROVISIONAL_IDENTITY"
    MISSING_IDENTITY_EVIDENCE = "MISSING_IDENTITY_EVIDENCE"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    SYMBOL_REUSE_CONFLICT = "SYMBOL_REUSE_CONFLICT"
    SYMBOL_CHANGE_UNRESOLVED = "SYMBOL_CHANGE_UNRESOLVED"
    ISIN_CONFLICT = "ISIN_CONFLICT"
    OVERLAPPING_IDENTITY_INTERVALS = "OVERLAPPING_IDENTITY_INTERVALS"
    IDENTITY_INTERVAL_GAP = "IDENTITY_INTERVAL_GAP"
    SERIES_TRANSITION_UNRESOLVED = "SERIES_TRANSITION_UNRESOLVED"
    LISTING_BOUNDARY_UNVERIFIED = "LISTING_BOUNDARY_UNVERIFIED"
    DELISTING_BOUNDARY_UNVERIFIED = "DELISTING_BOUNDARY_UNVERIFIED"
    SUSPENSION_BOUNDARY_UNVERIFIED = "SUSPENSION_BOUNDARY_UNVERIFIED"
    RELISTING_BOUNDARY_UNVERIFIED = "RELISTING_BOUNDARY_UNVERIFIED"
    OUTSIDE_ACTIVE_INTERVAL = "OUTSIDE_ACTIVE_INTERVAL"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    UNSUPPORTED_SECURITY_TYPE = "UNSUPPORTED_SECURITY_TYPE"


class MembershipState(StrEnum):
    ACTIVE_TRADABLE = "ACTIVE_TRADABLE"
    ACTIVE_SUSPENDED = "ACTIVE_SUSPENDED"
    PRE_LISTING = "PRE_LISTING"
    POST_DELISTING = "POST_DELISTING"
    TEMPORARILY_SUSPENDED = "TEMPORARILY_SUSPENDED"
    RELISTED = "RELISTED"
    SERIES_NOT_SUPPORTED = "SERIES_NOT_SUPPORTED"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    MEMBERSHIP_UNRESOLVED = "MEMBERSHIP_UNRESOLVED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class CertificationState(StrEnum):
    POINT_IN_TIME_UNIVERSE_CERTIFIED = "POINT_IN_TIME_UNIVERSE_CERTIFIED"
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    BLOCKED_MISSING_SECURITY_MASTER = "BLOCKED_MISSING_SECURITY_MASTER"
    BLOCKED_IDENTITY_AMBIGUITY = "BLOCKED_IDENTITY_AMBIGUITY"
    BLOCKED_SYMBOL_REUSE = "BLOCKED_SYMBOL_REUSE"
    BLOCKED_SYMBOL_CHANGE_EVIDENCE = "BLOCKED_SYMBOL_CHANGE_EVIDENCE"
    BLOCKED_LISTING_DELISTING_EVIDENCE = "BLOCKED_LISTING_DELISTING_EVIDENCE"
    BLOCKED_SUSPENSION_EVIDENCE = "BLOCKED_SUSPENSION_EVIDENCE"
    BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE = "BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SourceStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    INVENTORIED = "INVENTORIED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class EvidenceType(StrEnum):
    DAILY_BHAVCOPY = "DAILY_BHAVCOPY"
    MII_SECURITY_MASTER = "MII_SECURITY_MASTER"
    CURRENT_SECURITY_LIST = "CURRENT_SECURITY_LIST"
    SYMBOL_CHANGE_HISTORY = "SYMBOL_CHANGE_HISTORY"
    NAME_CHANGE_HISTORY = "NAME_CHANGE_HISTORY"
    LISTING_NOTICE = "LISTING_NOTICE"
    DELISTING_NOTICE = "DELISTING_NOTICE"
    SUSPENSION_NOTICE = "SUSPENSION_NOTICE"


class ConfidenceState(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OfficialSourceSpec:
    source_id: str
    evidence_type: EvidenceType
    url: str
    parser: str
    expected_segment: str
    effective_date: date | None = None
    current_only: bool = False


@dataclass(frozen=True, slots=True)
class SourceInventoryRecord:
    source_id: str
    evidence_type: EvidenceType
    source_path: str | None
    source_url: str
    official_host: bool
    sha256: str | None
    acquired_at: str | None
    covered_from: date | None
    covered_to: date | None
    file_format: str
    parser: str
    row_count: int
    admitted_records: int
    rejected_records: int
    status: SourceStatus
    limitations: tuple[str, ...]
    redirect_chain: tuple[str, ...] = ()
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class RejectedEvidenceRecord:
    source_id: str
    source_url: str
    reason_code: str
    detail: str
    row_number: int | None = None
    raw_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityIdentityRecord:
    identity_key: str
    exchange: str
    isin: str | None
    symbols: tuple[str, ...]
    series: tuple[str, ...]
    first_observed: date
    last_observed: date
    candle_rows: int
    identity_state: IdentityState
    secondary_issue_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    confidence: ConfidenceState


@dataclass(frozen=True, slots=True)
class IdentityIntervalRecord:
    identity_key: str
    symbol: str
    series: str
    valid_from: date
    valid_to: date
    source_id: str
    evidence_type: EvidenceType
    confidence: ConfidenceState
    admission_status: str
    observation_count: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolHistoryRecord:
    identity_key: str
    isin: str | None
    symbol: str
    series: str
    first_observed: date
    last_observed: date
    previous_symbol: str | None
    next_symbol: str | None
    continuity_state: str
    official_source_id: str | None


@dataclass(frozen=True, slots=True)
class SymbolReuseRecord:
    symbol: str
    series: str
    involved_isins: tuple[str, ...]
    interval_summaries: tuple[str, ...]
    intervals_overlap: bool
    official_evidence: tuple[str, ...]
    candle_count: int
    candidate_count: int
    final_classification: IdentityState


@dataclass(frozen=True, slots=True)
class SymbolChangeRecord:
    previous_symbol: str
    new_symbol: str
    isin_before: str | None
    isin_after: str | None
    effective_date: date | None
    official_source_id: str | None
    predecessor_identity: str
    successor_identity: str
    continuity_state: str
    canonical_rows_before: int
    canonical_rows_after: int
    overlap_days: int
    gap_days: int
    admission_decision: str


@dataclass(frozen=True, slots=True)
class BoundaryRecord:
    identity_key: str
    isin: str | None
    official_listing_date: date | None
    first_canonical_candle: date
    listing_discrepancy_days: int | None
    official_delisting_date: date | None
    last_canonical_candle: date
    delisting_discrepancy_days: int | None
    boundary_state: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuspensionRecord:
    identity_key: str
    suspended_from: date | None
    suspended_to: date | None
    restoration_date: date | None
    source_id: str | None
    status: str
    missing_sessions_explained: int


@dataclass(frozen=True, slots=True)
class MembershipIntervalRecord:
    identity_key: str
    symbol: str
    series: str
    valid_from: date
    valid_to: date
    membership_state: MembershipState
    source_id: str | None
    evidence_scope: str
    identity_days: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandleReconciliationRecord:
    year: int
    identity_state: IdentityState
    membership_state: MembershipState
    candle_rows: int
    distinct_identities: int
    source_hash_rows: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateExposureRecord:
    blocker: str
    affected_identities: int | None
    technical_candidates: int
    watchlist_candidates: int
    buy_candidates: int
    strong_buy_candidates: int
    approvals: int
    outcome_availability: str


@dataclass(frozen=True, slots=True)
class SurvivorshipRecord:
    metric: str
    count: int | None
    state: str
    explanation: str


@dataclass(frozen=True, slots=True)
class TimeBoundarySummary:
    latest_calendar_date: date | None
    latest_canonical_date: date | None
    latest_snapshot_date: date | None
    latest_official_master_date: date | None
    latest_identity_supported_date: date | None
    final_common_as_of_date: date | None
    analysis_end_date: date


@dataclass(frozen=True, slots=True)
class SourceSummary:
    official_sources_attempted: int
    sources_acquired: int
    sources_reused: int
    sources_failed: int
    records_parsed: int
    records_admitted: int
    records_rejected: int
    security_master_dates_covered: int
    security_master_dates_uncovered: int


@dataclass(frozen=True, slots=True)
class IdentitySummary:
    raw_symbols: int
    symbol_series_pairs: int
    isins: int
    governed_identities: int
    provisional_identities: int
    unresolved_identities: int
    ambiguous_identities: int
    symbol_reuse_conflicts: int
    symbol_changes_resolved: int
    symbol_changes_unresolved: int
    isin_conflicts: int
    overlapping_intervals: int
    interval_gaps: int


@dataclass(frozen=True, slots=True)
class MembershipSummary:
    identity_days_expected: int
    identity_days_certified: int
    active_tradable_identity_days: int
    suspended_identity_days: int
    unresolved_membership_days: int
    pre_listing_candle_rows: int
    post_delisting_candle_rows: int
    candles_outside_active_intervals: int


@dataclass(frozen=True, slots=True)
class YtdSummary:
    year: int
    latest_canonical_date: date | None
    included_in_certified_window: bool
    exclusion_reason: str | None
    canonical_rows: int
    observed_isin_identities: int
    missing_isin_rows: int
    governed_identities: int
    provisional_identities: int
    unresolved_identities: int
    active_universe_size: int | None
    symbol_changes: int | None
    listings: int | None
    delistings: int | None
    suspensions: int | None
    technical_candidates: int | None
    buy_candidates: int | None
    strong_buy_candidates: int | None


@dataclass(frozen=True, slots=True)
class CertificationSummary:
    primary_state: CertificationState
    secondary_blockers: tuple[CertificationState, ...]
    rationale: str
    thresholds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeIdentityReport:
    contract_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    time_boundaries: TimeBoundarySummary
    ytd_summary: YtdSummary
    source_summary: SourceSummary
    identity_summary: IdentitySummary
    membership_summary: MembershipSummary
    sources: tuple[SourceInventoryRecord, ...]
    rejected_evidence: tuple[RejectedEvidenceRecord, ...]
    identities: tuple[SecurityIdentityRecord, ...]
    identity_intervals: tuple[IdentityIntervalRecord, ...]
    symbol_history: tuple[SymbolHistoryRecord, ...]
    symbol_reuse: tuple[SymbolReuseRecord, ...]
    symbol_changes: tuple[SymbolChangeRecord, ...]
    listing_delisting: tuple[BoundaryRecord, ...]
    suspensions: tuple[SuspensionRecord, ...]
    membership_intervals: tuple[MembershipIntervalRecord, ...]
    candle_reconciliation: tuple[CandleReconciliationRecord, ...]
    candidate_exposure: tuple[CandidateExposureRecord, ...]
    survivorship: tuple[SurvivorshipRecord, ...]
    certification: CertificationSummary
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        raw = _jsonable(asdict(self))
        if not isinstance(raw, dict):
            raise TypeError("HTR-009A report must serialize to an object")
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


def valid_isin(value: str | None) -> bool:
    """Validate the structural form of an ISIN without inventing an identity."""

    if value is None:
        return False
    normalized = value.strip().upper()
    return len(normalized) == 12 and normalized[:2].isalpha() and normalized.isalnum()


def identity_interval_issues(
    intervals: tuple[tuple[date, date, str, str], ...],
) -> tuple[IdentityState, ...]:
    """Identify overlap, gap, and series-transition issues deterministically."""

    ordered = tuple(sorted(intervals, key=lambda item: (item[0], item[1], item[2])))
    issues: list[IdentityState] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current[0] <= previous[1]:
            issues.append(IdentityState.OVERLAPPING_IDENTITY_INTERVALS)
        elif current[0] > previous[1] + timedelta(days=1):
            issues.append(IdentityState.IDENTITY_INTERVAL_GAP)
        if current[3] != previous[3]:
            issues.append(IdentityState.SERIES_TRANSITION_UNRESOLVED)
    return tuple(dict.fromkeys(issues))


def classify_membership(
    trading_date: date,
    *,
    identity_resolved: bool,
    series_supported: bool,
    listing_date: date | None,
    delisting_date: date | None,
    suspension_intervals: tuple[tuple[date, date], ...] = (),
    relisting_date: date | None = None,
) -> MembershipState:
    """Classify membership only from explicit point-in-time boundaries."""

    if not identity_resolved:
        return MembershipState.IDENTITY_UNRESOLVED
    if not series_supported:
        return MembershipState.SERIES_NOT_SUPPORTED
    if listing_date is None:
        return MembershipState.MEMBERSHIP_UNRESOLVED
    if trading_date < listing_date:
        return MembershipState.PRE_LISTING
    if delisting_date is not None and trading_date > delisting_date:
        if relisting_date is not None and trading_date >= relisting_date:
            return MembershipState.RELISTED
        return MembershipState.POST_DELISTING
    if any(start <= trading_date <= end for start, end in suspension_intervals):
        return MembershipState.TEMPORARILY_SUSPENDED
    return MembershipState.ACTIVE_TRADABLE


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
    "BoundaryRecord",
    "CandidateExposureRecord",
    "CandleReconciliationRecord",
    "CertificationState",
    "CertificationSummary",
    "ConfidenceState",
    "EvidenceType",
    "HTR009A_CONTRACT_VERSION",
    "IdentityIntervalRecord",
    "IdentitySummary",
    "IdentityState",
    "MembershipIntervalRecord",
    "MembershipSummary",
    "MembershipState",
    "OfficialSourceSpec",
    "PRODUCTION_INFLUENCE",
    "PointInTimeIdentityReport",
    "RejectedEvidenceRecord",
    "SUPPORTED_SERIES",
    "SecurityIdentityRecord",
    "SourceInventoryRecord",
    "SourceSummary",
    "SourceStatus",
    "SuspensionRecord",
    "SurvivorshipRecord",
    "SymbolChangeRecord",
    "SymbolHistoryRecord",
    "SymbolReuseRecord",
    "TimeBoundarySummary",
    "YtdSummary",
    "valid_isin",
    "classify_membership",
    "identity_interval_issues",
]
