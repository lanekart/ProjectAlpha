from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
NO_FEATURE_CHANGES = True
NO_GATE_CHANGES = True
NO_APPROVAL_CHANGES = True
NO_WEIGHT_CHANGES = True
NO_SETUP_CHANGES = True
POINT_IN_TIME_ONLY = True

MOTA_VERSION = "MOTA_v1.0"
BASELINE_ID = "ALPHA_BASELINE_v1.0"
QUALITY_POLICY_VERSION = "MOTA_QUALITY_POLICY_v1.0"
CLUSTER_POLICY_VERSION = "MOTA_CLUSTER_POLICY_v1.0"
COMPARISON_POLICY_VERSION = "MOTA_ALPHA_COMPARISON_v1.0"
DEFAULT_OUTPUT = ".alpha/market_opportunity/MOTA_v1.0"


class OpportunityQuality(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    NOT_TRADABLE = "Not Tradable"

    @property
    def institutional(self) -> bool:
        return self in {OpportunityQuality.A_PLUS, OpportunityQuality.A}


class TrendState(StrEnum):
    UP_ALIGNED = "UP_ALIGNED"
    PRICE_ABOVE_EMA20 = "PRICE_ABOVE_EMA20"
    NON_ALIGNED = "NON_ALIGNED"
    UNKNOWN = "UNKNOWN"


class VolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class LiquidityState(StrEnum):
    INSTITUTIONAL = "INSTITUTIONAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    MINIMUM = "MINIMUM"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class DetectionStatus(StrEnum):
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    UNKNOWN_NOT_PERSISTED = "UNKNOWN_NOT_PERSISTED"


class OutcomeMaturity(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RawOpportunityOnset:
    opportunity_id: str
    symbol: str
    onset_date: date
    onset_sequence: int
    entry: Decimal
    reference_level: Decimal
    initial_stop: Decimal
    reasonable_target: Decimal
    prospective_rr: Decimal
    source_confidence: Decimal
    point_in_time_inputs: tuple[tuple[str, str], ...]
    dataset_version: str
    evidence_hash: str

    def input_value(self, key: str) -> str | None:
        return dict(self.point_in_time_inputs).get(key)


@dataclass(frozen=True, slots=True)
class TradabilityAssessment:
    tradable: bool
    liquidity_turnover: Decimal | None
    liquidity_state: LiquidityState
    trend_state: TrendState
    volatility_state: VolatilityState
    atr_percent: Decimal | None
    base_depth_percent: Decimal | None
    extension_percent: Decimal | None
    relative_volume: Decimal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpportunityQualityAssessment:
    quality: OpportunityQuality
    score: Decimal
    components: tuple[tuple[str, Decimal], ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class OpportunitySeed:
    onset: RawOpportunityOnset
    tradability: TradabilityAssessment
    quality: OpportunityQualityAssessment
    cluster_id: str
    cluster_explanation: str
    point_in_time_decision_hash: str


@dataclass(frozen=True, slots=True)
class OpportunityLifecycle:
    opportunity_id: str
    maturity: OutcomeMaturity
    available_forward_bars: int
    days_to_peak: int | None
    days_to_failure: int | None
    mfe_percent: Decimal | None
    mae_percent: Decimal | None
    rr_achieved: Decimal | None
    target_before_stop: bool | None
    stop_hit: bool | None
    exit_reason: str
    first_event_date: date | None


@dataclass(frozen=True, slots=True)
class MarketOpportunity:
    opportunity_id: str
    symbol: str
    onset_date: date
    entry: Decimal
    initial_stop: Decimal
    reasonable_target: Decimal
    prospective_rr: Decimal
    liquidity_turnover: Decimal | None
    liquidity_state: LiquidityState
    trend_state: TrendState
    volatility_state: VolatilityState
    quality: OpportunityQuality
    quality_score: Decimal
    quality_explanation: str
    cluster_id: str
    cluster_explanation: str
    market_regime: str
    days_to_peak: int | None
    days_to_failure: int | None
    mfe_percent: Decimal | None
    mae_percent: Decimal | None
    rr_achieved: Decimal | None
    target_before_stop: bool | None
    stop_hit: bool | None
    lifecycle_status: OutcomeMaturity
    available_forward_bars: int
    exit_reason: str
    first_event_date: date | None
    point_in_time_decision_hash: str


@dataclass(frozen=True, slots=True)
class OpportunityCalendarRecord:
    month: str
    sessions: int
    opportunities: int
    institutional_quality: int
    a_plus: int
    grade_a: int
    grade_b: int
    grade_c: int
    not_tradable: int
    opportunities_per_session: Decimal | None
    institutional_per_session: Decimal | None


@dataclass(frozen=True, slots=True)
class OpportunityDensityRecord:
    period_type: str
    period: str
    sessions: int
    opportunities: int
    high_quality: int
    medium_quality: int
    low_quality: int
    not_tradable: int
    opportunities_per_session: Decimal | None


@dataclass(frozen=True, slots=True)
class QualityDistributionRecord:
    quality: OpportunityQuality
    opportunities: int
    population_percent: Decimal
    mature_outcomes: int
    target_before_stop_count: int
    target_before_stop_rate: Decimal | None
    stop_hit_rate: Decimal | None
    average_realized_r: Decimal | None
    average_mfe_percent: Decimal | None
    average_mae_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class OpportunityClusterSummary:
    cluster_id: str
    opportunities: int
    institutional_quality: int
    population_percent: Decimal
    median_prospective_rr: Decimal | None
    mature_outcomes: int
    target_before_stop_rate: Decimal | None
    average_realized_r: Decimal | None
    average_mfe_percent: Decimal | None
    average_mae_percent: Decimal | None
    assignment_dimensions: str
    future_outcomes_used_for_assignment: bool = False


@dataclass(frozen=True, slots=True)
class AlphaComparisonRecord:
    opportunity_id: str
    symbol: str
    onset_date: date
    quality: OpportunityQuality
    institutional_quality: bool
    detected_status: DetectionStatus
    detection_date: date | None
    detection_delay_sessions: int | None
    candidate_created: bool
    candidate_date: date | None
    candidate_delay_sessions: int | None
    candidate_signal: str | None
    institutional_approved: bool
    approval_date: date | None
    executed: bool
    execution_date: date | None
    matching_window_sessions: int
    matching_explanation: str


@dataclass(frozen=True, slots=True)
class CaptureStatistics:
    market_opportunities: int
    institutional_quality_opportunities: int
    detected_opportunities: int
    directional_candidates: int
    approved_opportunities: int
    executed_opportunities: int
    overall_detection_recall_percent: Decimal | None
    institutional_detection_recall_percent: Decimal | None
    overall_candidate_recall_percent: Decimal | None
    institutional_candidate_recall_percent: Decimal | None
    institutional_approval_recall_percent: Decimal | None
    institutional_execution_recall_percent: Decimal | None
    opportunity_capture_rate_percent: Decimal | None
    move_capture_percent: Decimal | None
    capital_capture_percent: Decimal | None
    detection_trace_complete: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class MarketSupplySummary:
    total_opportunities: int
    institutional_quality_opportunities: int
    mature_outcomes: int
    months_observed: int
    average_opportunities_per_month: Decimal | None
    median_opportunities_per_month: Decimal | None
    average_institutional_opportunities_per_month: Decimal | None
    median_institutional_opportunities_per_month: Decimal | None
    best_month: str
    best_month_opportunities: int
    worst_month: str
    worst_month_opportunities: int
    institutional_average_realized_r: Decimal | None
    other_average_realized_r: Decimal | None
    quality_tier_monotonic: bool | None
    institutional_quality_status: str
    authoritative_market_regime_available: bool


@dataclass(frozen=True, slots=True)
class MOTAManifest:
    audit_version: str
    baseline_id: str
    baseline_manifest_hash: str
    source_commit: str
    warehouse_version: str
    candidate_version: str
    feature_version: str
    opportunity_definition_version: str
    quality_policy_version: str
    cluster_policy_version: str
    comparison_policy_version: str
    horizon_sessions: int
    matching_window_sessions: int
    source_hashes: Mapping[str, str]
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    production_influence: bool = PRODUCTION_INFLUENCE
    no_feature_changes: bool = NO_FEATURE_CHANGES
    no_gate_changes: bool = NO_GATE_CHANGES
    no_approval_changes: bool = NO_APPROVAL_CHANGES
    no_weight_changes: bool = NO_WEIGHT_CHANGES
    no_setup_changes: bool = NO_SETUP_CHANGES
    point_in_time_only: bool = POINT_IN_TIME_ONLY

    def __post_init__(self) -> None:
        controls = (
            not self.production_influence,
            self.no_feature_changes,
            self.no_gate_changes,
            self.no_approval_changes,
            self.no_weight_changes,
            self.no_setup_changes,
            self.point_in_time_only,
        )
        if not all(controls):
            raise ValueError("MOTA isolation guardrails cannot be disabled")
        object.__setattr__(
            self,
            "source_hashes",
            MappingProxyType(dict(sorted(self.source_hashes.items()))),
        )
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )


@dataclass(frozen=True, slots=True)
class MarketOpportunityTruthReport:
    manifest: MOTAManifest
    opportunities: tuple[MarketOpportunity, ...]
    calendar: tuple[OpportunityCalendarRecord, ...]
    density: tuple[OpportunityDensityRecord, ...]
    quality_distribution: tuple[QualityDistributionRecord, ...]
    clusters: tuple[OpportunityClusterSummary, ...]
    alpha_comparison: tuple[AlphaComparisonRecord, ...]
    capture_statistics: CaptureStatistics
    supply_summary: MarketSupplySummary


__all__ = [name for name in globals() if not name.startswith("_")]
