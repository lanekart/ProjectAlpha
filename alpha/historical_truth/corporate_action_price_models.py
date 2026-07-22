"""Immutable HTR-009B corporate-action and price-basis contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR009B_CONTRACT_VERSION = "HTR-009B-v1.0.0"
PRODUCTION_INFLUENCE = False


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    DIVIDEND = "DIVIDEND"
    FACE_VALUE_CHANGE = "FACE_VALUE_CHANGE"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    AMALGAMATION = "AMALGAMATION"
    SCHEME_OF_ARRANGEMENT = "SCHEME_OF_ARRANGEMENT"
    SPIN_OFF = "SPIN_OFF"
    SECURITY_REPLACEMENT = "SECURITY_REPLACEMENT"
    ISIN_CHANGE = "ISIN_CHANGE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    RELISTING = "RELISTING"
    SHARE_CANCELLATION = "SHARE_CANCELLATION"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"


class ActionAdmissionState(StrEnum):
    ADMITTED = "ADMITTED"
    PROVISIONAL = "PROVISIONAL"
    REJECTED = "REJECTED"
    CONFLICTING = "CONFLICTING"


class EvidenceConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class SourceStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    INVENTORIED = "INVENTORIED"


class FailureCode(StrEnum):
    OFFICIAL_SOURCE_NOT_FOUND = "OFFICIAL_SOURCE_NOT_FOUND"
    HTTP_ACCESS_DENIED = "HTTP_ACCESS_DENIED"
    HTTP_RATE_LIMITED = "HTTP_RATE_LIMITED"
    INVALID_CONTENT_TYPE = "INVALID_CONTENT_TYPE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    PARSER_FAILED = "PARSER_FAILED"
    WRONG_MARKET_SEGMENT = "WRONG_MARKET_SEGMENT"
    WRONG_SECURITY = "WRONG_SECURITY"
    WRONG_DATE_RANGE = "WRONG_DATE_RANGE"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    CONFLICTING_EVENT = "CONFLICTING_EVENT"
    INVALID_FACTOR = "INVALID_FACTOR"
    AMBIGUOUS_FACTOR = "AMBIGUOUS_FACTOR"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AdjustmentFactorState(StrEnum):
    KNOWN_OFFICIAL = "KNOWN_OFFICIAL"
    DERIVED_FROM_OFFICIAL_TERMS = "DERIVED_FROM_OFFICIAL_TERMS"
    NOT_REQUIRED = "NOT_REQUIRED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
    CONFLICTING = "CONFLICTING"


class AdjustmentDirection(StrEnum):
    BACKWARD = "BACKWARD"
    FORWARD = "FORWARD"


class PriceBasisState(StrEnum):
    RAW_UNADJUSTED = "RAW_UNADJUSTED"
    BACKWARD_ADJUSTED = "BACKWARD_ADJUSTED"
    FORWARD_ADJUSTED = "FORWARD_ADJUSTED"
    TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"
    MIXED_PRICE_BASIS = "MIXED_PRICE_BASIS"
    ADJUSTMENT_REQUIRED_NOT_APPLIED = "ADJUSTMENT_REQUIRED_NOT_APPLIED"
    ADJUSTMENT_FACTOR_UNKNOWN = "ADJUSTMENT_FACTOR_UNKNOWN"
    IDENTITY_TRANSITION_UNRESOLVED = "IDENTITY_TRANSITION_UNRESOLVED"
    NO_ADJUSTMENT_REQUIRED = "NO_ADJUSTMENT_REQUIRED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class ContinuityType(StrEnum):
    SAME_IDENTITY = "SAME_IDENTITY"
    PREDECESSOR_SUCCESSOR = "PREDECESSOR_SUCCESSOR"
    MULTIPLE_SUCCESSORS = "MULTIPLE_SUCCESSORS"
    NEW_IDENTITY_REQUIRED = "NEW_IDENTITY_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class ContaminationState(StrEnum):
    NOT_EXPOSED = "NOT_EXPOSED"
    EXPOSED_ADJUSTED = "EXPOSED_ADJUSTED"
    EXPOSED_UNADJUSTED = "EXPOSED_UNADJUSTED"
    EXPOSED_UNKNOWN_FACTOR = "EXPOSED_UNKNOWN_FACTOR"
    LINKAGE_UNAVAILABLE = "LINKAGE_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class CertificationState(StrEnum):
    CORPORATE_ACTION_PRICE_BASIS_CERTIFIED = "CORPORATE_ACTION_PRICE_BASIS_CERTIFIED"
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    BLOCKED_MISSING_CORPORATE_ACTION_EVIDENCE = (
        "BLOCKED_MISSING_CORPORATE_ACTION_EVIDENCE"
    )
    BLOCKED_UNKNOWN_ADJUSTMENT_FACTORS = "BLOCKED_UNKNOWN_ADJUSTMENT_FACTORS"
    BLOCKED_MIXED_PRICE_BASIS = "BLOCKED_MIXED_PRICE_BASIS"
    BLOCKED_IDENTITY_TRANSITIONS = "BLOCKED_IDENTITY_TRANSITIONS"
    BLOCKED_CONFLICTING_EVENTS = "BLOCKED_CONFLICTING_EVENTS"
    BLOCKED_POINT_IN_TIME_SAFETY = "BLOCKED_POINT_IN_TIME_SAFETY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class CorporateActionSourceSpec:
    source_id: str
    source_family: str
    url: str
    covered_start: date
    covered_end: date
    parser: str = "nse_corporate_actions_json_v1"


@dataclass(frozen=True, slots=True)
class CorporateActionSourceRecord:
    source_id: str
    source_family: str
    source_url: str
    official_host: bool
    document_id: str
    retrieval_timestamp: str | None
    http_status: int | None
    content_type: str | None
    redirects: tuple[str, ...]
    byte_size: int
    sha256: str | None
    covered_start: date
    covered_end: date
    parser: str
    immutable_path: str | None
    records_inspected: int
    events_parsed: int
    events_admitted: int
    events_rejected: int
    status: SourceStatus
    reuse_state: str
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    consumer_usage: str = "HTR-009B_DIAGNOSTIC_ONLY"
    price_basis: str = "OFFICIAL_EVENT_TERMS"
    known_limitations: str = ""


@dataclass(frozen=True, slots=True)
class CorporateActionRejection:
    source_id: str
    source_location: str
    failure_code: FailureCode
    failure_detail: str
    row_number: int | None = None
    raw_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    action_id: str
    exchange: str
    governed_identity_id: str | None
    symbol: str
    series: str
    isin: str | None
    action_type: CorporateActionType
    purpose: str
    announcement_date: date | None
    record_date: date | None
    ex_date: date
    effective_date: date
    old_face_value: float | None
    new_face_value: float | None
    ratio_numerator: float | None
    ratio_denominator: float | None
    cash_amount: float | None
    rights_price: float | None
    old_quantity: float | None
    new_quantity: float | None
    predecessor_identity: str | None
    successor_identity: str | None
    price_adjustment_required: bool
    adjustment_factor_state: AdjustmentFactorState
    adjustment_factor: float | None
    source_id: str
    source_location: str
    admission_state: ActionAdmissionState
    confidence_state: EvidenceConfidence


@dataclass(frozen=True, slots=True)
class CorporateActionLineage:
    action_id: str
    source_id: str
    source_sha256: str
    source_url: str
    parser: str
    row_number: int


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    factor_id: str
    action_id: str
    identity_key: str
    effective_date: date
    direction: AdjustmentDirection
    price_factor: float | None
    quantity_factor: float | None
    state: AdjustmentFactorState
    source_id: str
    calculation_version: str
    reference_price: float | None = None
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class PriceBasisInterval:
    identity_key: str
    valid_from: date
    valid_to: date
    state: PriceBasisState
    action_ids: tuple[str, ...]
    known_factor_count: int
    unknown_factor_count: int
    raw_row_count: int
    adjusted_row_count: int
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdjustedCandleSummary:
    identity_key: str
    raw_rows: int
    adjusted_rows: int
    first_date: date
    last_date: date
    cumulative_price_factor: float
    cumulative_quantity_factor: float
    action_ids: tuple[str, ...]
    price_basis_state: PriceBasisState


@dataclass(frozen=True, slots=True)
class PriceDiscontinuity:
    action_id: str
    identity_key: str
    symbol: str
    action_type: CorporateActionType
    ex_date: date
    previous_session: date | None
    action_session: date | None
    previous_close: float | None
    action_open: float | None
    action_close: float | None
    raw_gap_pct: float | None
    theoretical_adjusted_gap_pct: float | None
    atr_before: float | None
    raw_gap_atr: float | None
    adjusted_gap_atr: float | None
    volume_change_pct: float | None
    false_breakout_risk: bool
    false_breakdown_risk: bool
    continuity_restored: bool
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndicatorContamination:
    action_id: str
    identity_key: str
    symbol: str
    ex_date: date
    moving_average_state: ContaminationState
    atr_state: ContaminationState
    fibonacci_state: ContaminationState
    support_resistance_state: ContaminationState
    false_breakout_risk: bool
    false_breakdown_risk: bool
    raw_adjusted_divergence_pct: float | None
    explanation: str


@dataclass(frozen=True, slots=True)
class StopContamination:
    candidate_id: str
    identity_key: str | None
    symbol: str | None
    candidate_date: date | None
    action_id: str | None
    raw_stop: float | None
    adjusted_stop: float | None
    raw_stop_distance_pct: float | None
    adjusted_stop_distance_pct: float | None
    raw_stop_distance_atr: float | None
    adjusted_stop_distance_atr: float | None
    deepest_support_distorted: bool
    nearest_support_changed: bool
    risk_reward_changed: bool
    gate_result_may_be_contaminated: bool
    state: ContaminationState
    explanation: str


@dataclass(frozen=True, slots=True)
class IdentityTransition:
    transition_id: str
    predecessor_identity: str | None
    successor_identity: str | None
    old_symbol: str | None
    new_symbol: str | None
    old_isin: str | None
    new_isin: str | None
    action_type: CorporateActionType
    effective_date: date
    exchange_ratio: str | None
    continuity_type: ContinuityType
    histories_may_be_linked: bool
    price_comparison_valid: bool
    new_identity_required: bool
    official_source: str
    confidence_state: EvidenceConfidence
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateCorporateActionExposure:
    candidate_id: str
    identity_key: str | None
    symbol: str | None
    candidate_date: date | None
    setup: str | None
    verdict: str
    candidate_count: int
    action_in_lookback: bool | None
    action_type: CorporateActionType | None
    price_basis_state: PriceBasisState
    corporate_action_risk: ContaminationState
    identity_transition_state: ContinuityType
    adjustment_factor_state: AdjustmentFactorState
    raw_adjusted_divergence: float | None
    indicator_contamination_state: ContaminationState
    stop_contamination_state: ContaminationState
    target_contamination_state: ContaminationState
    outcome_contamination_state: ContaminationState
    evidence_availability: str


@dataclass(frozen=True, slots=True)
class CoverageCutoffs:
    calendar_date: date | None
    canonical_candle_date: date | None
    snapshot_date: date | None
    corporate_action_evidence_date: date | None
    identity_transition_evidence_date: date | None
    final_common_audit_date: date
    ytd_2026_events: int
    ytd_2026_admitted_events: int
    ytd_2026_certified: bool
    ytd_2026_blocker: str | None


@dataclass(frozen=True, slots=True)
class SourceSummary:
    attempted: int
    acquired: int
    reused: int
    failed: int
    rejected: int
    uncovered_years: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EventSummary:
    parsed: int
    admitted: int
    rejected: int
    conflicting: int
    counts_by_type: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class FactorSummary:
    known: int
    derived: int
    ambiguous: int
    unknown: int
    invalid: int
    conflicting: int


@dataclass(frozen=True, slots=True)
class PriceBasisSummary:
    raw_candle_rows: int
    adjusted_candle_rows: int
    identities_fully_adjusted: int
    identities_partially_adjusted: int
    mixed_basis_identities: int
    unresolved_action_intervals: int


@dataclass(frozen=True, slots=True)
class ContinuitySummary:
    raw_discontinuities: int
    adjusted_discontinuities: int
    false_breakout_risks: int
    false_breakdown_risks: int
    atr_contamination_cases: int
    moving_average_contamination_cases: int
    support_resistance_contamination_cases: int


@dataclass(frozen=True, slots=True)
class IdentityTransitionSummary:
    resolved: int
    unresolved: int
    predecessor_successor_links: int
    symbol_changes_resolved: int
    isin_transitions_resolved: int
    mergers: int
    demergers: int
    schemes: int


@dataclass(frozen=True, slots=True)
class CandidateExposureSummary:
    technical: int
    watchlist: int
    buy: int
    strong_buy: int
    approvals: int
    stop_loss_exposed: int
    target_exposed: int
    outcome_exposed: int
    identity_transition_exposed: int
    linkage_available: bool


@dataclass(frozen=True, slots=True)
class CorporateActionCertification:
    primary_state: CertificationState
    secondary_blockers: tuple[CertificationState, ...]
    rationale: str
    thresholds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorporateActionPriceReport:
    contract_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    cutoffs: CoverageCutoffs
    sources: tuple[CorporateActionSourceRecord, ...]
    rejected_evidence: tuple[CorporateActionRejection, ...]
    actions: tuple[CorporateActionEvent, ...]
    lineage: tuple[CorporateActionLineage, ...]
    factors: tuple[AdjustmentFactor, ...]
    price_basis_intervals: tuple[PriceBasisInterval, ...]
    adjusted_candle_summary: tuple[AdjustedCandleSummary, ...]
    price_discontinuities: tuple[PriceDiscontinuity, ...]
    indicator_contamination: tuple[IndicatorContamination, ...]
    stop_contamination: tuple[StopContamination, ...]
    identity_transitions: tuple[IdentityTransition, ...]
    candidate_exposure: tuple[CandidateCorporateActionExposure, ...]
    source_summary: SourceSummary
    event_summary: EventSummary
    factor_summary: FactorSummary
    price_basis_summary: PriceBasisSummary
    continuity_summary: ContinuitySummary
    identity_transition_summary: IdentityTransitionSummary
    candidate_exposure_summary: CandidateExposureSummary
    certification: CorporateActionCertification
    report_sha256: str

    def calculated_sha256(self) -> str:
        payload = _jsonable(asdict(self))
        payload["report_sha256"] = ""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()


def stable_id(*parts: object) -> str:
    raw = "|".join("" if part is None else str(part).strip() for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()


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
    "ActionAdmissionState",
    "AdjustedCandleSummary",
    "AdjustmentDirection",
    "AdjustmentFactor",
    "AdjustmentFactorState",
    "CandidateCorporateActionExposure",
    "CandidateExposureSummary",
    "CertificationState",
    "ContaminationState",
    "ContinuitySummary",
    "ContinuityType",
    "CorporateActionCertification",
    "CorporateActionEvent",
    "CorporateActionLineage",
    "CorporateActionPriceReport",
    "CorporateActionRejection",
    "CorporateActionSourceRecord",
    "CorporateActionSourceSpec",
    "CorporateActionType",
    "CoverageCutoffs",
    "EvidenceConfidence",
    "EventSummary",
    "FactorSummary",
    "FailureCode",
    "HTR009B_CONTRACT_VERSION",
    "IdentityTransition",
    "IdentityTransitionSummary",
    "IndicatorContamination",
    "PRODUCTION_INFLUENCE",
    "PriceBasisInterval",
    "PriceBasisState",
    "PriceBasisSummary",
    "PriceDiscontinuity",
    "SourceStatus",
    "SourceSummary",
    "StopContamination",
    "stable_id",
]
