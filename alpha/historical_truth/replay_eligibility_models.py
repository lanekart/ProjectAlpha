"""Typed domain contracts for HTR-008 replay eligibility certification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR008_CONTRACT_VERSION = "HTR-008-v1.0.0"
PRODUCTION_INFLUENCE = False
CANONICAL_MINIMUM_HISTORY_SESSIONS = 200


class ReplayReadinessClassification(StrEnum):
    REPLAY_READY = "REPLAY_READY"
    INSUFFICIENT_VALID_HISTORY = "INSUFFICIENT_VALID_HISTORY"
    IDENTITY_AMBIGUITY = "IDENTITY_AMBIGUITY"
    SYMBOL_REUSE_CONFLICT = "SYMBOL_REUSE_CONFLICT"
    SYMBOL_CHANGE_DISCONTINUITY = "SYMBOL_CHANGE_DISCONTINUITY"
    ISIN_CONFLICT = "ISIN_CONFLICT"
    IDENTITY_INTERVAL_OVERLAP = "IDENTITY_INTERVAL_OVERLAP"
    IDENTITY_INTERVAL_GAP = "IDENTITY_INTERVAL_GAP"
    LISTING_BOUNDARY_UNVERIFIED = "LISTING_BOUNDARY_UNVERIFIED"
    DELISTING_BOUNDARY_UNVERIFIED = "DELISTING_BOUNDARY_UNVERIFIED"
    SUSPENSION_BOUNDARY_UNVERIFIED = "SUSPENSION_BOUNDARY_UNVERIFIED"
    INTERNAL_CANDLE_GAPS = "INTERNAL_CANDLE_GAPS"
    INVALID_CANDLE_CONTAMINATION = "INVALID_CANDLE_CONTAMINATION"
    UNSUPPORTED_SERIES = "UNSUPPORTED_SERIES"
    SOURCE_LINEAGE_INCOMPLETE = "SOURCE_LINEAGE_INCOMPLETE"
    POINT_IN_TIME_UNIVERSE_MISSING = "POINT_IN_TIME_UNIVERSE_MISSING"
    SNAPSHOT_EVIDENCE_INSUFFICIENT = "SNAPSHOT_EVIDENCE_INSUFFICIENT"
    CORPORATE_ACTION_CONTAMINATION = "CORPORATE_ACTION_CONTAMINATION"
    SURVIVORSHIP_RISK = "SURVIVORSHIP_RISK"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNKNOWN_BLOCKER = "UNKNOWN_BLOCKER"


class MissingSessionClassification(StrEnum):
    BEFORE_LISTING = "BEFORE_LISTING"
    AFTER_DELISTING = "AFTER_DELISTING"
    OFFICIAL_SUSPENSION = "OFFICIAL_SUSPENSION"
    NOT_IN_POINT_IN_TIME_UNIVERSE = "NOT_IN_POINT_IN_TIME_UNIVERSE"
    UNSUPPORTED_SERIES = "UNSUPPORTED_SERIES"
    OFFICIAL_ARCHIVE_UNAVAILABLE = "OFFICIAL_ARCHIVE_UNAVAILABLE"
    ARCHIVE_ROW_ABSENT = "ARCHIVE_ROW_ABSENT"
    PARSER_REJECTED = "PARSER_REJECTED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    IDENTITY_RESOLUTION_FAILED = "IDENTITY_RESOLUTION_FAILED"
    CANONICAL_INGESTION_FAILED = "CANONICAL_INGESTION_FAILED"
    NO_TRADE_EVIDENCE = "NO_TRADE_EVIDENCE"
    UNEXPLAINED_INTERNAL_GAP = "UNEXPLAINED_INTERNAL_GAP"


class CorporateActionSeverity(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"
    UNKNOWN = "UNKNOWN"


class SurvivorshipRisk(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"
    UNKNOWN = "UNKNOWN"


class CertificationState(StrEnum):
    REPLAY_ELIGIBILITY_CERTIFIED = "REPLAY_ELIGIBILITY_CERTIFIED"
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    BLOCKED_IDENTITY_INTEGRITY = "BLOCKED_IDENTITY_INTEGRITY"
    BLOCKED_CONTINUITY_INTEGRITY = "BLOCKED_CONTINUITY_INTEGRITY"
    BLOCKED_SOURCE_LINEAGE = "BLOCKED_SOURCE_LINEAGE"
    BLOCKED_CORPORATE_ACTION_RISK = "BLOCKED_CORPORATE_ACTION_RISK"
    BLOCKED_POINT_IN_TIME_UNIVERSE = "BLOCKED_POINT_IN_TIME_UNIVERSE"
    BLOCKED_SURVIVORSHIP_RISK = "BLOCKED_SURVIVORSHIP_RISK"
    BLOCKED_CONFLICTING_EVIDENCE = "BLOCKED_CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EligibilityAuditPolicy:
    minimum_history_sessions: int = CANONICAL_MINIMUM_HISTORY_SESSIONS
    minimum_continuity_ratio: float = 0.95
    maximum_unexplained_gap_sessions: int = 5
    require_governed_identity: bool = True
    require_point_in_time_universe: bool = True
    require_source_hash: bool = True
    require_detailed_lineage_for_certification: bool = True
    require_corporate_action_evidence: bool = True
    require_snapshot_parity: bool = True

    def __post_init__(self) -> None:
        if self.minimum_history_sessions < 1:
            raise ValueError("minimum history sessions must be positive")
        if not 0 <= self.minimum_continuity_ratio <= 1:
            raise ValueError("minimum continuity ratio must be between zero and one")
        if self.maximum_unexplained_gap_sessions < 0:
            raise ValueError("maximum unexplained gap sessions cannot be negative")


@dataclass(frozen=True, slots=True)
class SecurityEligibilityRecord:
    identity_key: str
    exchange: str
    symbols: tuple[str, ...]
    series: tuple[str, ...]
    isins: tuple[str, ...]
    identity_governed: bool
    active_identity_candidates_max: int
    first_observed_session: date
    last_observed_session: date
    total_candle_rows: int
    valid_candle_sessions: int
    invalid_candle_sessions: int
    duplicate_sessions: int
    expected_sessions: int
    observed_sessions: int
    explained_missing_sessions: int
    unexplained_missing_sessions: int
    coverage_ratio: float
    longest_continuous_valid_session_streak: int
    longest_unexplained_internal_gap: int
    unexplained_internal_gap_count: int
    first_20_session_date: date | None
    first_50_session_date: date | None
    first_100_session_date: date | None
    first_150_session_date: date | None
    first_200_session_date: date | None
    first_500_session_date: date | None
    first_1000_session_date: date | None
    replay_eligible_start_date: date | None
    replay_eligible_security_days: int
    source_hash_rows: int
    detailed_lineage_rows: int
    snapshot_evidence_valid: bool
    corporate_action_count: int
    corporate_action_severity: CorporateActionSeverity
    survivorship_risk: SurvivorshipRisk
    primary_classification: ReplayReadinessClassification
    secondary_issue_codes: tuple[str, ...]

    @property
    def symbol(self) -> str:
        return self.symbols[-1]

    @property
    def ready(self) -> bool:
        return self.primary_classification is ReplayReadinessClassification.REPLAY_READY


@dataclass(frozen=True, slots=True)
class CorporateActionRiskRecord:
    identity_key: str
    symbol: str
    isin: str | None
    event_date: date
    event_type: str
    source_sha256: str | None
    previous_valid_close: float | None
    next_valid_open: float | None
    next_valid_close: float | None
    raw_overnight_discontinuity: float | None
    expected_adjustment_factor: float | None
    adjusted_canonical_prices_available: bool
    benchmark_consumes_raw_prices: bool
    false_signal_risks: tuple[str, ...]
    severity: CorporateActionSeverity


@dataclass(frozen=True, slots=True)
class EligibilityFunnelRecord:
    trading_date: date
    canonical_securities_observed: int
    supported_series: int
    identity_resolved: int
    inside_governed_active_interval: int
    valid_candle_evidence: int
    minimum_history_met: int
    acceptable_continuity: int
    acceptable_lineage: int
    acceptable_corporate_action_risk: int
    snapshot_available_and_verified: int
    point_in_time_universe_supported: int
    final_replay_ready_population: int


@dataclass(frozen=True, slots=True)
class CandidateExposureRecord:
    certification_class: str
    technical_candidates: int
    buy_candidates: int
    strong_buy_candidates: int
    unresolved_issues: bool
    blocking_contamination: bool
    corporate_action_evidence_missing: bool
    survivorship_risk: bool


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    distinct_raw_symbols: int
    distinct_symbol_series_pairs: int
    distinct_isins: int
    governed_identities: int
    unresolved_identities: int
    ambiguous_identities: int
    symbol_reuse_cases: int
    supported_symbol_changes: int
    unsupported_symbol_changes: int
    identity_overlaps: int
    identity_gaps: int


@dataclass(frozen=True, slots=True)
class DepthSummary:
    identity_count: int
    at_least_20: int
    at_least_50: int
    at_least_100: int
    at_least_150: int
    at_least_200: int
    at_least_500: int
    at_least_1000: int
    at_least_2000: int
    minimum: int
    maximum: int
    mean: float
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    p95: float
    p99: float


@dataclass(frozen=True, slots=True)
class ContinuitySummary:
    expected_security_sessions: int
    observed_security_sessions: int
    valid_security_sessions: int
    invalid_security_sessions: int
    explained_missing_security_sessions: int
    unexplained_missing_security_sessions: int
    identities_with_zero_unexplained_gaps: int
    identities_with_unexplained_gaps: int


@dataclass(frozen=True, slots=True)
class CandleQualitySummary:
    high_below_low: int
    open_above_high: int
    open_below_low: int
    close_above_high: int
    close_below_low: int
    negative_price: int
    negative_volume: int
    invalid_zero_price: int
    duplicate_rows: int
    conflicting_rows: int
    unsupported_exchange_rows: int
    unsupported_series_rows: int
    unsupported_series_ohlc_exceptions: int
    missing_source_hash_rows: int
    missing_detailed_lineage_rows: int
    lineage_checksum_disagreement_rows: int
    snapshot_mismatch_dates: int


@dataclass(frozen=True, slots=True)
class SnapshotAuditSummary:
    expected_dates: int
    present_dates: int
    valid_dates: int
    missing_dates: tuple[date, ...]
    invalid_dates: tuple[date, ...]
    inventory_sha256: str


@dataclass(frozen=True, slots=True)
class EligibilityReconciliation:
    benchmark_eligible_securities: int
    benchmark_eligible_security_days: int
    identities_with_200_raw_rows: int
    identities_with_200_valid_sessions: int
    identities_passing_identity: int
    identities_passing_continuity: int
    identities_passing_lineage: int
    identities_passing_corporate_actions: int
    final_replay_ready_identities: int
    final_replay_ready_security_days: int
    eligible_security_discrepancy: int
    eligible_security_day_discrepancy: int


@dataclass(frozen=True, slots=True)
class CertificationSummary:
    primary_state: CertificationState
    secondary_blockers: tuple[CertificationState, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class BaselineBenchmarkSummary:
    benchmark_output: str
    run_id: str
    repository_commit: str
    database_sha256: str
    snapshot_inventory_sha256: str
    sessions: int
    eligible_securities: int
    eligible_security_days: int
    technical_candidates: int
    buy_candidates: int
    strong_buy_candidates: int
    institutional_approvals: int
    trades: int
    rejection_reasons: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ReplayEligibilityIntegrityReport:
    contract_version: str
    production_influence: bool
    database_path: str
    calendar_report_path: str
    snapshot_root: str
    start_date: date
    end_date: date
    policy: EligibilityAuditPolicy
    baseline: BaselineBenchmarkSummary
    population: PopulationSummary
    depth: DepthSummary
    continuity: ContinuitySummary
    candle_quality: CandleQualitySummary
    snapshots: SnapshotAuditSummary
    reconciliation: EligibilityReconciliation
    certification: CertificationSummary
    records: tuple[SecurityEligibilityRecord, ...]
    corporate_actions: tuple[CorporateActionRiskRecord, ...]
    funnel: tuple[EligibilityFunnelRecord, ...]
    candidate_exposure: tuple[CandidateExposureRecord, ...]
    annual_coverage: tuple[tuple[int, float], ...]
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = _json_value(asdict(self))
        if not isinstance(payload, dict):
            raise TypeError("HTR-008 report must serialize to an object")
        if not include_hash:
            payload.pop("report_sha256", None)
        return payload

    def calculated_sha256(self) -> str:
        encoded = json.dumps(
            self.payload(include_hash=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


def _json_value(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


__all__ = [
    "CANONICAL_MINIMUM_HISTORY_SESSIONS",
    "HTR008_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "BaselineBenchmarkSummary",
    "CandidateExposureRecord",
    "CandleQualitySummary",
    "CertificationState",
    "CertificationSummary",
    "ContinuitySummary",
    "CorporateActionRiskRecord",
    "CorporateActionSeverity",
    "DepthSummary",
    "EligibilityAuditPolicy",
    "EligibilityFunnelRecord",
    "EligibilityReconciliation",
    "MissingSessionClassification",
    "PopulationSummary",
    "ReplayEligibilityIntegrityReport",
    "ReplayReadinessClassification",
    "SecurityEligibilityRecord",
    "SnapshotAuditSummary",
    "SurvivorshipRisk",
]
