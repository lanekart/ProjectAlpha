from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
NO_POLICY_RELAXATION = True
CANONICAL_POLICY_ID = "ALPHA_CANONICAL_v1.0"
INTEGRITY_AUDIT_VERSION = "canonical-integrity-audit-v1.0"
LEGACY_DATASET_VERSION = "LEGACY_DATASET"


class FailureCategory(StrEnum):
    DATA_MISSING = "DATA_MISSING"
    DATA_INVALID = "DATA_INVALID"
    IDENTITY_FAILURE = "IDENTITY_FAILURE"
    INDICATOR_FAILURE = "INDICATOR_FAILURE"
    SETUP_FAILURE = "SETUP_FAILURE"
    SCORING_FAILURE = "SCORING_FAILURE"
    ENTRY_TIMING_FAILURE = "ENTRY_TIMING_FAILURE"
    TRADE_PLAN_FAILURE = "TRADE_PLAN_FAILURE"
    APPROVAL_FAILURE = "APPROVAL_FAILURE"
    OUTCOME_FAILURE = "OUTCOME_FAILURE"
    SERIALIZATION_FAILURE = "SERIALIZATION_FAILURE"
    UNKNOWN = "UNKNOWN"


class EvidenceClass(StrEnum):
    CSV_TRADE_LEVEL = "CSV_TRADE_LEVEL"
    CSV_SUMMARY = "CSV_SUMMARY"
    SCREENSHOT_DERIVED = "SCREENSHOT_DERIVED"


class ParityClassification(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    SEMANTIC_MATCH = "SEMANTIC_MATCH"
    ALPHA_CANDIDATE_REJECTED = "ALPHA_CANDIDATE_REJECTED"
    ALPHA_CANDIDATE_DIFFERENT_SCORE = "ALPHA_CANDIDATE_DIFFERENT_SCORE"
    ALPHA_SETUP_NOT_DETECTED = "ALPHA_SETUP_NOT_DETECTED"
    ALPHA_ENTRY_TIMING_DIFFERENCE = "ALPHA_ENTRY_TIMING_DIFFERENCE"
    ALPHA_TRADE_PLAN_DIFFERENCE = "ALPHA_TRADE_PLAN_DIFFERENCE"
    ALPHA_RUNTIME_BLOCKED = "ALPHA_RUNTIME_BLOCKED"
    DATA_DIFFERENCE = "DATA_DIFFERENCE"
    PINE_APPROXIMATION = "PINE_APPROXIMATION"
    UNMATCHED = "UNMATCHED"


class CoverageClassification(StrEnum):
    CAPTURED = "CAPTURED"
    PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED"
    REJECTED = "REJECTED"
    MISSED = "MISSED"
    UNSCORABLE = "UNSCORABLE"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"
    DATA_BLOCKED = "DATA_BLOCKED"


class ZeroTradeReason(StrEnum):
    NO_TRADES_BECAUSE_NO_SETUP = "NO_TRADES_BECAUSE_NO_SETUP"
    NO_TRADES_BECAUSE_WEAK_SCORE = "NO_TRADES_BECAUSE_WEAK_SCORE"
    NO_TRADES_BECAUSE_TIMING = "NO_TRADES_BECAUSE_TIMING"
    NO_TRADES_BECAUSE_TRADE_PLAN = "NO_TRADES_BECAUSE_TRADE_PLAN"
    NO_TRADES_BECAUSE_INSTITUTIONAL_GATE = "NO_TRADES_BECAUSE_INSTITUTIONAL_GATE"
    NO_TRADES_BECAUSE_RUNTIME_FAILURE = "NO_TRADES_BECAUSE_RUNTIME_FAILURE"
    NO_TRADES_BECAUSE_DATA_UNAVAILABLE = "NO_TRADES_BECAUSE_DATA_UNAVAILABLE"


class EconomicProblem(StrEnum):
    SIGNAL_QUALITY_PROBLEM = "SIGNAL_QUALITY_PROBLEM"
    SETUP_RECOGNITION_PROBLEM = "SETUP_RECOGNITION_PROBLEM"
    ENTRY_TIMING_PROBLEM = "ENTRY_TIMING_PROBLEM"
    TRADE_PLAN_PROBLEM = "TRADE_PLAN_PROBLEM"
    APPROVAL_POLICY_PROBLEM = "APPROVAL_POLICY_PROBLEM"
    OUTCOME_CONSTRUCTION_PROBLEM = "OUTCOME_CONSTRUCTION_PROBLEM"
    RUNTIME_INTEGRITY_PROBLEM = "RUNTIME_INTEGRITY_PROBLEM"
    DATA_QUALITY_PROBLEM = "DATA_QUALITY_PROBLEM"
    PINE_PARITY_PROBLEM = "PINE_PARITY_PROBLEM"


@dataclass(frozen=True, slots=True)
class FrozenPolicyManifest:
    policy_id: str
    source_commit: str
    weights: Mapping[str, str]
    thresholds: Mapping[str, str]
    setup_versions: tuple[str, ...]
    entry_timing_version: str
    trade_plan_version: str
    approval_policy_version: str
    outcome_definition_version: str
    dataset_version: str
    mte_provider_version: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.policy_id != CANONICAL_POLICY_ID:
            raise ValueError("integrity audit policy must remain ALPHA_CANONICAL_v1.0")
        if self.production_influence:
            raise ValueError("integrity audit cannot influence production")
        object.__setattr__(self, "weights", _frozen_mapping(self.weights))
        object.__setattr__(self, "thresholds", _frozen_mapping(self.thresholds))
        object.__setattr__(self, "setup_versions", tuple(self.setup_versions))


@dataclass(frozen=True, slots=True)
class RuntimeFailureRecord:
    trading_date: date
    symbol: str
    candidate_id: str
    pipeline_stage: str
    category: FailureCategory
    exception_type: str
    exception_message: str
    source_file: str
    source_line: int | None
    input_state: Mapping[str, str]
    missing_fields: tuple[str, ...]
    provider_state: str
    dataset_version: str
    deterministic_reproduction: bool
    failure_hash: str
    directly_triggered: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "category", FailureCategory(self.category))
        object.__setattr__(self, "input_state", _frozen_mapping(self.input_state))
        object.__setattr__(self, "missing_fields", tuple(sorted(self.missing_fields)))


@dataclass(frozen=True, slots=True)
class RuntimeFailureGroup:
    failure_hash: str
    category: FailureCategory
    pipeline_stage: str
    exception_type: str
    exception_message: str
    failure_days: int
    affected_candidates: int
    directly_triggering_candidates: int
    repeated: bool


@dataclass(frozen=True, slots=True)
class RuntimeReplayComparison:
    before_failure_days: int
    after_failure_days: int
    before_affected_candidates: int
    after_affected_candidates: int
    before_scored_candidates: int
    after_scored_candidates: int
    before_approval_candidates: int
    after_approval_candidates: int
    before_institutional_approvals: int
    after_institutional_approvals: int
    repair: str
    repair_scope: str
    policy_mutated: bool = False

    def __post_init__(self) -> None:
        if self.policy_mutated:
            raise ValueError("runtime replay cannot mutate canonical policy")


@dataclass(frozen=True, slots=True)
class PineExperimentMetadata:
    symbol: str
    exchange: str
    chart_timeframe: str
    start_date: date
    end_date: date
    entry_threshold: Decimal | None
    strategy_family: str
    setup_selection: str
    commission: Decimal | None
    slippage: Decimal | None
    position_size: Decimal | None
    market_regime_setting: str
    sector_setting: str
    script_version: str
    framework_version: str
    evidence_class: EvidenceClass
    source_file: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        object.__setattr__(self, "evidence_class", EvidenceClass(self.evidence_class))


@dataclass(frozen=True, slots=True)
class PineTrade:
    trade_id: str
    symbol: str
    exchange: str
    entry_date: date
    entry_bar: int | None
    setup_family: str
    strategy_family: str
    score: Decimal | None
    entry_price: Decimal | None
    stop_price: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    exit_date: date | None
    exit_price: Decimal | None
    net_return_pct: Decimal | None
    evidence_class: EvidenceClass
    source_file: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        object.__setattr__(self, "evidence_class", EvidenceClass(self.evidence_class))


@dataclass(frozen=True, slots=True)
class CanonicalTradeEvent:
    candidate_id: str
    symbol: str
    observed_on: date
    score: Decimal | None
    setup: str
    setup_state: str
    strategy: str
    entry: Decimal | None
    stop: Decimal | None
    targets: tuple[Decimal | None, Decimal | None, Decimal | None]
    final_signal: str
    final_gate: str
    rejection_reason: str | None
    runtime_blocked: bool = False


@dataclass(frozen=True, slots=True)
class PineAlphaTradeMatch:
    pine_trade_id: str
    alpha_candidate_id: str | None
    symbol: str
    classification: ParityClassification
    pine_entry_date: date
    alpha_candidate_date: date | None
    pine_score: Decimal | None
    alpha_score: Decimal | None
    score_delta: Decimal | None
    pine_setup: str
    alpha_setup: str | None
    pine_strategy: str
    alpha_strategy: str | None
    pine_entry: Decimal | None
    alpha_entry: Decimal | None
    pine_stop: Decimal | None
    alpha_stop: Decimal | None
    pine_targets: tuple[Decimal | None, Decimal | None, Decimal | None]
    alpha_targets: tuple[Decimal | None, Decimal | None, Decimal | None]
    final_alpha_gate: str | None
    alpha_rejection_reason: str | None
    outcome_difference: str | None


@dataclass(frozen=True, slots=True)
class ParityDivergenceSummary:
    divergence_stage: str
    count: int
    share: Decimal


@dataclass(frozen=True, slots=True)
class OpportunityDefinition:
    name: str
    minimum_return: Decimal
    forward_horizon: int

    def __post_init__(self) -> None:
        if self.minimum_return <= 0 or self.forward_horizon < 1:
            raise ValueError("opportunity definition requires positive bounds")


@dataclass(frozen=True, slots=True)
class MajorOpportunityEvent:
    event_id: str
    symbol: str
    start_date: date
    breakout_date: date
    peak_date: date
    forward_horizon: int
    forward_return: Decimal
    event_definition: str
    maximum_forward_return: Decimal
    time_to_peak: int
    maximum_adverse_excursion_before_peak: Decimal
    volume_expansion: Decimal | None
    base_length: int
    trend_state: str
    start_price: Decimal
    peak_price: Decimal
    dataset_version: str


@dataclass(frozen=True, slots=True)
class OpportunityCoverageRecord:
    event_id: str
    symbol: str
    classification: CoverageClassification
    alpha_candidate_id: str | None
    entry_delay_sessions: int | None
    captured_return: Decimal | None
    captured_r: Decimal | None
    share_of_total_move: Decimal | None
    exit_efficiency: Decimal | None
    stop_efficiency: Decimal | None
    time_in_trade: int | None
    mfe: Decimal | None
    mae: Decimal | None
    primary_blocker: str | None
    secondary_blocker: str | None
    score: Decimal | None
    setup_state: str | None
    timing_state: str | None
    trade_plan_grade: str | None
    stop_distance: Decimal | None
    minimum_rr: Decimal | None
    volume_confirmation: str | None
    trend_confirmation: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "classification", CoverageClassification(self.classification)
        )


@dataclass(frozen=True, slots=True)
class ZeroTradeDiagnostic:
    symbol: str
    sessions_examined: int
    potential_setup_count: int
    technical_candidate_count: int
    scored_candidate_count: int
    buy_strong_buy_count: int
    timing_valid_count: int
    trade_plan_valid_count: int
    institutional_approval_count: int
    runtime_failures: int
    primary_blocker: str
    secondary_blocker: str | None
    explanation: ZeroTradeReason

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "explanation", ZeroTradeReason(self.explanation))


@dataclass(frozen=True, slots=True)
class CaseStudy:
    requested_symbol: str
    resolved_symbol: str | None
    event_ids: tuple[str, ...]
    major_move_definition: str
    event_dates: str
    candidate_creation_status: str
    setup_detection: str
    component_scores: Mapping[str, str]
    final_score: Decimal | None
    verdict: str
    entry_timing_state: str
    approval_result: str
    trade_plan_result: str
    runtime_state: str
    coverage_classification: str
    primary_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requested_symbol", self.requested_symbol.strip().upper()
        )
        object.__setattr__(self, "event_ids", tuple(self.event_ids))
        object.__setattr__(
            self, "component_scores", _frozen_mapping(self.component_scores)
        )


@dataclass(frozen=True, slots=True)
class IntegrityAuditSummary:
    runtime_failure_days_before: int
    runtime_failure_days_after: int
    affected_candidates_before: int
    affected_candidates_after: int
    pine_trades_imported: int
    exact_parity_rate: Decimal | None
    semantic_parity_rate: Decimal | None
    major_opportunities: int
    captured: int
    partially_captured: int
    rejected: int
    missed: int
    runtime_blocked: int
    data_blocked: int
    largest_divergence_stage: str
    highest_value_missed_opportunity: str
    primary_bottleneck: EconomicProblem
    secondary_bottlenecks: tuple[EconomicProblem, ...]


@dataclass(frozen=True, slots=True)
class CanonicalIntegrityAuditReport:
    audit_id: str
    generated_at: datetime
    policy: FrozenPolicyManifest
    runtime_failures: tuple[RuntimeFailureRecord, ...]
    runtime_groups: tuple[RuntimeFailureGroup, ...]
    runtime_replay: RuntimeReplayComparison
    pine_metadata: tuple[PineExperimentMetadata, ...]
    pine_trades: tuple[PineTrade, ...]
    parity_matches: tuple[PineAlphaTradeMatch, ...]
    divergences: tuple[ParityDivergenceSummary, ...]
    opportunities: tuple[MajorOpportunityEvent, ...]
    coverage: tuple[OpportunityCoverageRecord, ...]
    zero_trades: tuple[ZeroTradeDiagnostic, ...]
    case_studies: tuple[CaseStudy, ...]
    summary: IntegrityAuditSummary
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("integrity report cannot influence production")
        for name in (
            "runtime_failures",
            "runtime_groups",
            "pine_metadata",
            "pine_trades",
            "parity_matches",
            "divergences",
            "opportunities",
            "coverage",
            "zero_trades",
            "case_studies",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


def to_primitive(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_primitive(getattr(value, item.name)) for item in fields(value)
        }
    return value


def _frozen_mapping(value: Mapping[str, object]) -> MappingProxyType[str, str]:
    return MappingProxyType(
        dict(
            sorted((str(key).strip(), str(item).strip()) for key, item in value.items())
        )
    )


__all__ = [
    "CANONICAL_POLICY_ID",
    "INTEGRITY_AUDIT_VERSION",
    "LEGACY_DATASET_VERSION",
    "NO_POLICY_RELAXATION",
    "PRODUCTION_INFLUENCE",
    "CanonicalIntegrityAuditReport",
    "CanonicalTradeEvent",
    "CaseStudy",
    "CoverageClassification",
    "EconomicProblem",
    "EvidenceClass",
    "FailureCategory",
    "FrozenPolicyManifest",
    "IntegrityAuditSummary",
    "MajorOpportunityEvent",
    "OpportunityCoverageRecord",
    "OpportunityDefinition",
    "ParityClassification",
    "ParityDivergenceSummary",
    "PineAlphaTradeMatch",
    "PineExperimentMetadata",
    "PineTrade",
    "RuntimeFailureGroup",
    "RuntimeFailureRecord",
    "RuntimeReplayComparison",
    "ZeroTradeDiagnostic",
    "ZeroTradeReason",
    "to_primitive",
]
