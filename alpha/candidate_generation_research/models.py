from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
NO_AUTOMATIC_DEPLOYMENT = True
NO_APPROVAL_RELAXATION = True
NO_WEIGHT_CHANGES = True
NO_FUTURE_LEAKAGE = True
POINT_IN_TIME_ONLY = True
HOLDOUT_REQUIRED = True
CANDIDATE_EXPLOSION_PENALTY = True
LEGACY_DATA_IS_PROVISIONAL = True
TRADINGVIEW_IS_SECONDARY_VALIDATOR = True

CANONICAL_POLICY_ID = "ALPHA_CANONICAL_v1.0"
RESEARCH_POLICY_ID = "ALPHA_CANDIDATE_RESEARCH_v1.0"
RESEARCH_VERSION = "candidate-generation-research-v1.0"
DATASET_VERSION = "LEGACY_DATASET"


class OpportunityFamily(StrEnum):
    BREAKOUT_FROM_BASE = "BREAKOUT_FROM_BASE"
    VOLUME_BREAKOUT = "VOLUME_BREAKOUT"
    TREND_REVERSAL = "TREND_REVERSAL"
    EMA_RECLAIM = "EMA_RECLAIM"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"
    RETEST_HOLD = "RETEST_HOLD"
    VOLATILITY_CONTRACTION_BREAKOUT = "VOLATILITY_CONTRACTION_BREAKOUT"
    RELATIVE_STRENGTH_BREAKOUT = "RELATIVE_STRENGTH_BREAKOUT"
    FAILED_BREAKOUT_REVERSAL = "FAILED_BREAKOUT_REVERSAL"
    EARLY_ACCUMULATION = "EARLY_ACCUMULATION"
    NO_TRADABLE_ONSET = "NO_TRADABLE_ONSET"


class StageStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"
    DATA_BLOCKED = "DATA_BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CandidateFailureReason(StrEnum):
    SETUP_FAMILY_NOT_SUPPORTED = "SETUP_FAMILY_NOT_SUPPORTED"
    PATTERN_THRESHOLD_TOO_STRICT = "PATTERN_THRESHOLD_TOO_STRICT"
    LOOKBACK_MISMATCH = "LOOKBACK_MISMATCH"
    PIVOT_CONFIRMATION_DELAY = "PIVOT_CONFIRMATION_DELAY"
    VOLUME_RULE_FAILED = "VOLUME_RULE_FAILED"
    TREND_RULE_FAILED = "TREND_RULE_FAILED"
    RELATIVE_STRENGTH_RULE_FAILED = "RELATIVE_STRENGTH_RULE_FAILED"
    EXTENSION_RULE_FAILED = "EXTENSION_RULE_FAILED"
    LIQUIDITY_RULE_FAILED = "LIQUIDITY_RULE_FAILED"
    MISSING_FEATURE = "MISSING_FEATURE"
    IDENTITY_OR_CORPORATE_ACTION_BLOCK = "IDENTITY_OR_CORPORATE_ACTION_BLOCK"
    TIMING_WINDOW_MISSED = "TIMING_WINDOW_MISSED"
    CANDIDATE_ADAPTER_DEFECT = "CANDIDATE_ADAPTER_DEFECT"
    UNKNOWN = "UNKNOWN"


class TimingClassification(StrEnum):
    ON_TIME = "ON_TIME"
    SLIGHTLY_LATE = "SLIGHTLY_LATE"
    MATERIALLY_LATE = "MATERIALLY_LATE"
    EXTENDED_BEFORE_DETECTION = "EXTENDED_BEFORE_DETECTION"
    MISSED_TIMING_WINDOW = "MISSED_TIMING_WINDOW"
    NO_CANDIDATE = "NO_CANDIDATE"


class CandidateCoverage(StrEnum):
    CAPTURED_BY_CANONICAL = "CAPTURED_BY_CANONICAL"
    PARTIALLY_CAPTURED_BY_CANONICAL = "PARTIALLY_CAPTURED_BY_CANONICAL"
    CANONICAL_CANDIDATE_REJECTED = "CANONICAL_CANDIDATE_REJECTED"
    CANONICAL_SETUP_MISSED = "CANONICAL_SETUP_MISSED"
    CANONICAL_TIMING_MISSED = "CANONICAL_TIMING_MISSED"
    CANONICAL_TRADE_PLAN_FAILED = "CANONICAL_TRADE_PLAN_FAILED"
    DATA_BLOCKED = "DATA_BLOCKED"
    NOT_ACTUALLY_TRADABLE = "NOT_ACTUALLY_TRADABLE"


class ZeroCandidateExplanation(StrEnum):
    NO_TRADABLE_OPPORTUNITY = "NO_TRADABLE_OPPORTUNITY"
    SETUP_VOCABULARY_GAP = "SETUP_VOCABULARY_GAP"
    THRESHOLD_TOO_STRICT = "THRESHOLD_TOO_STRICT"
    DETECTION_TOO_LATE = "DETECTION_TOO_LATE"
    TIMING_WINDOW_MISSED = "TIMING_WINDOW_MISSED"
    DATA_BLOCKED = "DATA_BLOCKED"
    CANONICAL_BEHAVIOR_CORRECT = "CANONICAL_BEHAVIOR_CORRECT"


class CandidatePartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class VariantFamily(StrEnum):
    RECOGNITION_TOLERANCE = "RECOGNITION_TOLERANCE"
    SETUP_VOCABULARY = "SETUP_VOCABULARY"
    TIMING_WINDOW = "TIMING_WINDOW"
    CANDIDATE_CREATION = "CANDIDATE_CREATION"


class PolicyProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    DEVELOPMENT_PASS = "DEVELOPMENT_PASS"
    VALIDATION_PASS = "VALIDATION_PASS"
    HOLDOUT_PASS = "HOLDOUT_PASS"
    PROMOTE_TO_POLICY_REVIEW = "PROMOTE_TO_POLICY_REVIEW"
    REJECTED = "REJECTED"
    MORE_EVIDENCE = "MORE_EVIDENCE"


class PineCandidateParity(StrEnum):
    PINE_AND_ALPHA_AGREE = "PINE_AND_ALPHA_AGREE"
    PINE_DETECTS_EARLIER = "PINE_DETECTS_EARLIER"
    PINE_DETECTS_DIFFERENT_SETUP = "PINE_DETECTS_DIFFERENT_SETUP"
    PINE_ONLY_APPROXIMATION = "PINE_ONLY_APPROXIMATION"
    ALPHA_ONLY_DETECTION = "ALPHA_ONLY_DETECTION"
    DATA_DIFFERENCE = "DATA_DIFFERENCE"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True, slots=True)
class CandidateResearchManifest:
    policy_id: str
    parent_policy_id: str
    source_commit: str
    dataset_version: str
    candidate_engine_version: str
    setup_engine_version: str
    timing_engine_version: str
    score_version: str
    approval_policy_version: str
    trade_plan_version: str
    outcome_version: str
    research_thresholds: Mapping[str, str]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.parent_policy_id != CANONICAL_POLICY_ID:
            raise ValueError("candidate research must preserve the canonical parent")
        if self.production_influence:
            raise ValueError("candidate research cannot influence production")
        object.__setattr__(
            self,
            "research_thresholds",
            MappingProxyType(dict(sorted(self.research_thresholds.items()))),
        )


@dataclass(frozen=True, slots=True)
class PointInTimeFeatureSnapshot:
    symbol: str
    observed_on: date
    sequence: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    prior_close: Decimal | None
    prior_high: Decimal | None
    resistance_20: Decimal | None
    support_20: Decimal | None
    ema_20: Decimal | None
    prior_ema_20: Decimal | None
    ema_50: Decimal | None
    atr_14: Decimal | None
    volume_ratio_20: Decimal | None
    average_turnover_20: Decimal | None
    base_width: Decimal | None
    recent_range_ratio: Decimal | None
    prior_range_ratio: Decimal | None
    return_20: Decimal | None
    relative_strength_20: Decimal | None
    close_location: Decimal | None
    recent_low_10: Decimal | None
    prior_breakout: bool
    input_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if self.sequence < 0:
            raise ValueError("feature sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class TradableOpportunityOnset:
    onset_id: str
    forward_event_id: str | None
    symbol: str
    onset_date: date
    onset_sequence: int
    event_family: OpportunityFamily
    setup_evidence: tuple[str, ...]
    entry_trigger: Decimal
    reference_level: Decimal
    prospective_stop: Decimal
    prospective_target: Decimal
    prospective_rr: Decimal
    extension_state: str
    liquidity_state: str
    confidence: Decimal
    point_in_time_inputs: Mapping[str, str]
    dataset_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "event_family", OpportunityFamily(self.event_family))
        object.__setattr__(self, "setup_evidence", tuple(self.setup_evidence))
        object.__setattr__(
            self,
            "point_in_time_inputs",
            MappingProxyType(dict(sorted(self.point_in_time_inputs.items()))),
        )
        if not self.prospective_stop < self.entry_trigger < self.prospective_target:
            raise ValueError("tradable onset requires ordered stop, entry, and target")
        if self.prospective_rr <= 0:
            raise ValueError("tradable onset requires positive prospective reward/risk")


@dataclass(frozen=True, slots=True)
class CandidateFunnelRecord:
    event_id: str
    onset_id: str | None
    symbol: str
    onset_date: date | None
    event_family: str
    tradable_onset: StageStatus
    canonical_setup_recognized: StageStatus
    canonical_candidate_created: StageStatus
    candidate_scored: StageStatus
    verdict_assigned: StageStatus
    timing_actionable: StageStatus
    trade_plan_feasible: StageStatus
    institutional_gate_evaluated: StageStatus
    canonical_candidate_id: str | None
    failure_reason: CandidateFailureReason | None
    coverage: CandidateCoverage
    evidence_limitation: str | None


@dataclass(frozen=True, slots=True)
class SetupRecognitionMetric:
    setup_family: str
    compatible_tradable_onsets: int
    canonical_detections: int
    false_negatives: int
    false_positives: int
    precision: Decimal | None
    recall: Decimal | None
    median_detection_delay: Decimal | None
    median_extension_at_detection: Decimal | None
    captured_forward_move_share: Decimal | None


@dataclass(frozen=True, slots=True)
class CandidateTimingRecord:
    event_id: str
    onset_id: str
    symbol: str
    earliest_tradable_date: date
    canonical_candidate_date: date | None
    delay_sessions: int | None
    entry_timing_state_at_onset: str
    entry_timing_state_at_candidate: str
    extension_at_candidate: Decimal | None
    remaining_forward_move: Decimal | None
    prospective_rr_at_onset: Decimal
    prospective_rr_at_candidate: Decimal | None
    classification: TimingClassification


@dataclass(frozen=True, slots=True)
class MissedCandidateAttribution:
    event_id: str
    onset_id: str | None
    symbol: str
    coverage: CandidateCoverage
    primary_blocker: str
    secondary_blocker: str | None
    canonical_candidate_date: date | None
    evidence: str


@dataclass(frozen=True, slots=True)
class CandidateVariantDefinition:
    variant_id: str
    family: VariantFamily
    description: str
    supported_families: tuple[OpportunityFamily, ...]
    minimum_confidence: Decimal
    minimum_volume_ratio: Decimal
    maximum_extension: Decimal
    minimum_rr: Decimal
    duplicate_cooldown_sessions: int
    maximum_candidates_per_day: int


@dataclass(frozen=True, slots=True)
class CandidateVariantResult:
    variant_id: str
    variant_family: VariantFamily
    partition: CandidatePartition
    candidates: int
    trading_days: int
    candidates_per_day: Decimal
    candidates_per_month: Decimal
    candidate_precision: Decimal | None
    candidate_recall: Decimal | None
    forward_expectancy_after_costs: Decimal | None
    false_candidate_rate: Decimal | None
    duplicate_candidate_rate: Decimal
    sector_concentration: Decimal | None
    symbol_concentration: Decimal | None
    turnover: Decimal | None
    trade_plan_feasibility: Decimal | None
    tradable_onset_coverage: Decimal | None
    major_move_capture_rate: Decimal | None
    average_prospective_rr: Decimal | None
    maximum_drawdown_proxy: Decimal | None
    explosion_penalty: Decimal
    stability: str
    passed: bool
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChronologicalValidationResult:
    variant_id: str
    development_pass: bool
    validation_pass: bool
    holdout_pass: bool
    selected_without_holdout: bool
    holdout_opened_after_selection: bool
    status: PolicyProposalStatus
    reason: str


@dataclass(frozen=True, slots=True)
class ZeroCandidateDiagnostic:
    symbol: str
    sessions_examined: int
    forward_move_events: int
    tradable_onsets: int
    canonical_setup_detections: int
    canonical_candidates: int
    best_near_setup: str
    primary_recognition_blocker: str
    secondary_recognition_blocker: str | None
    earliest_near_candidate_date: date | None
    explanation: ZeroCandidateExplanation


@dataclass(frozen=True, slots=True)
class PineLogicalTradeAudit:
    logical_entry_id: str
    symbol: str
    entry_date: date
    entry_quantity: Decimal
    exit_leg_id: str
    exit_date: date | None
    exit_quantity: Decimal
    remaining_quantity: Decimal
    forced_boundary_exit: bool
    issue: str
    source_file: str


@dataclass(frozen=True, slots=True)
class PineCandidateParityRecord:
    pine_trade_id: str
    symbol: str
    pine_entry_date: date
    pine_setup: str
    onset_id: str | None
    canonical_candidate_id: str | None
    classification: PineCandidateParity
    explanation: str


@dataclass(frozen=True, slots=True)
class CandidateCaseStudy:
    requested_symbol: str
    resolved_symbol: str | None
    forward_move_definition: str
    onset_date: date | None
    setup_family: str
    base_or_reversal_evidence: str
    volume_evidence: str
    trend_evidence: str
    relative_strength_evidence: str
    prospective_stop: Decimal | None
    prospective_target: Decimal | None
    prospective_rr: Decimal | None
    canonical_setup_result: str
    canonical_candidate_result: str
    canonical_timing_result: str
    candidate_variant_results: tuple[str, ...]
    coverage_classification: str
    primary_reason: str


@dataclass(frozen=True, slots=True)
class CandidatePolicyProposal:
    policy_id: str
    parent_policy: str
    variant_family: str | None
    setup_definitions: tuple[str, ...]
    candidate_creation_rules: tuple[str, ...]
    timing_rules: tuple[str, ...]
    evidence_partitions: tuple[str, ...]
    candidate_counts: Mapping[str, int]
    recall: Mapping[str, str]
    precision: Mapping[str, str]
    expectancy: Mapping[str, str]
    drawdown: Mapping[str, str]
    major_move_coverage: Mapping[str, str]
    false_candidate_rate: Mapping[str, str]
    validation_status: str
    holdout_status: str
    status: PolicyProposalStatus
    manifest_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("candidate policy proposal cannot deploy automatically")
        for name in (
            "candidate_counts",
            "recall",
            "precision",
            "expectancy",
            "drawdown",
            "major_move_coverage",
            "false_candidate_rate",
        ):
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(sorted(getattr(self, name).items()))),
            )


@dataclass(frozen=True, slots=True)
class CandidateResearchSummary:
    forward_move_events: int
    tradable_onsets: int
    tradable_event_count: int
    non_tradable_event_count: int
    future_moves_actually_tradable_share: Decimal | None
    canonical_setup_recall: Decimal | None
    canonical_candidate_recall: Decimal | None
    median_candidate_delay: Decimal | None
    primary_setup_blocker: str
    primary_timing_blocker: str
    variants_tested: int
    best_validated_variant: str
    candidate_explosion_risk: str
    kalyan_classification: str
    pc_jeweller_classification: str
    promotion_blockers: tuple[str, ...]
    median_onset_to_peak_sessions: Decimal | None = None
    median_pre_entry_mae: Decimal | None = None
    median_prospective_rr: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CandidateResearchReport:
    audit_id: str
    generated_at: datetime
    manifest: CandidateResearchManifest
    forward_move_events: tuple[object, ...]
    onsets: tuple[TradableOpportunityOnset, ...]
    funnel: tuple[CandidateFunnelRecord, ...]
    setup_metrics: tuple[SetupRecognitionMetric, ...]
    timing_metrics: tuple[CandidateTimingRecord, ...]
    missed_attribution: tuple[MissedCandidateAttribution, ...]
    variant_results: tuple[CandidateVariantResult, ...]
    validations: tuple[ChronologicalValidationResult, ...]
    zero_candidates: tuple[ZeroCandidateDiagnostic, ...]
    pine_logical_trades: tuple[PineLogicalTradeAudit, ...]
    pine_candidate_parity: tuple[PineCandidateParityRecord, ...]
    case_studies: tuple[CandidateCaseStudy, ...]
    policy_proposal: CandidatePolicyProposal
    summary: CandidateResearchSummary
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("candidate research report cannot influence production")
        for name in (
            "forward_move_events",
            "onsets",
            "funnel",
            "setup_metrics",
            "timing_metrics",
            "missed_attribution",
            "variant_results",
            "validations",
            "zero_candidates",
            "pine_logical_trades",
            "pine_candidate_parity",
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


__all__ = [
    "CANONICAL_POLICY_ID",
    "CANDIDATE_EXPLOSION_PENALTY",
    "DATASET_VERSION",
    "HOLDOUT_REQUIRED",
    "LEGACY_DATA_IS_PROVISIONAL",
    "NO_APPROVAL_RELAXATION",
    "NO_AUTOMATIC_DEPLOYMENT",
    "NO_FUTURE_LEAKAGE",
    "NO_WEIGHT_CHANGES",
    "POINT_IN_TIME_ONLY",
    "PRODUCTION_INFLUENCE",
    "RESEARCH_POLICY_ID",
    "RESEARCH_VERSION",
    "TRADINGVIEW_IS_SECONDARY_VALIDATOR",
    "CandidateCaseStudy",
    "CandidateCoverage",
    "CandidateFailureReason",
    "CandidateFunnelRecord",
    "CandidatePartition",
    "CandidatePolicyProposal",
    "CandidateResearchManifest",
    "CandidateResearchReport",
    "CandidateResearchSummary",
    "CandidateTimingRecord",
    "CandidateVariantDefinition",
    "CandidateVariantResult",
    "ChronologicalValidationResult",
    "MissedCandidateAttribution",
    "OpportunityFamily",
    "PineCandidateParity",
    "PineCandidateParityRecord",
    "PineLogicalTradeAudit",
    "PointInTimeFeatureSnapshot",
    "PolicyProposalStatus",
    "SetupRecognitionMetric",
    "StageStatus",
    "TimingClassification",
    "TradableOpportunityOnset",
    "VariantFamily",
    "ZeroCandidateDiagnostic",
    "ZeroCandidateExplanation",
    "to_primitive",
]
