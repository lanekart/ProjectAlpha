"""Immutable domain models for point-in-time feature attribution research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

PRODUCTION_INFLUENCE = False
NO_WEIGHT_CHANGES = True
NO_THRESHOLD_CHANGES = True
NO_SETUP_CHANGES = True
NO_APPROVAL_RELAXATION = True
NO_AUTOMATIC_PROMOTION = True
NO_FUTURE_LEAKAGE = True
POINT_IN_TIME_ONLY = True
HOLDOUT_REQUIRED = True
LEGACY_DATA_IS_PROVISIONAL = True

RESEARCH_VERSION = "point-in-time-feature-attribution-v1.0"
FEATURE_ENGINE_VERSION = "point-in-time-feature-engine-v1.0"
OUTCOME_DEFINITION_VERSION = "onset-outcomes-stop-first-v1.0"
CANONICAL_POLICY_ID = "ALPHA_CANONICAL_v1.0"
CANDIDATE_RESEARCH_VERSION = "ALPHA_CANDIDATE_RESEARCH_v1.0"
SETUP_DISCOVERY_VERSION = "SDE_v1.0"
PRIMARY_OUTCOME = "TARGET_BEFORE_STOP"
SECONDARY_OUTCOMES = (
    "POSITIVE_AFTER_COSTS_60D",
    "ACHIEVED_2R",
    "HIGH_QUALITY_WINNER",
)
OUTCOME_DEFINITION_COUPLED_FEATURES = frozenset(
    {
        "prospective_stop_distance",
        "prospective_target_distance",
        "prospective_reward_risk",
    }
)


class ResearchCohort(StrEnum):
    ALL_MARKET_OPPORTUNITIES = "ALL_MARKET_OPPORTUNITIES"
    ALL_TRADABLE_ONSETS = "ALL_TRADABLE_ONSETS"
    LINKED_HINDSIGHT = "LINKED_HINDSIGHT"
    CANONICAL_CANDIDATES = "CANONICAL_CANDIDATES"
    CANONICAL_MISSES = "CANONICAL_MISSES"
    CANONICAL_REJECTIONS = "CANONICAL_REJECTIONS"
    CAPTURED_OR_PARTIALLY_CAPTURED = "CAPTURED_OR_PARTIALLY_CAPTURED"
    NON_TRADABLE_HINDSIGHT_EVENTS = "NON_TRADABLE_HINDSIGHT_EVENTS"


class EvidencePartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class FeatureGroup(StrEnum):
    PRICE_STRUCTURE = "PRICE_STRUCTURE"
    TREND_PERSISTENCE = "TREND_PERSISTENCE"
    VOLUME_TURNOVER = "VOLUME_TURNOVER"
    VOLATILITY = "VOLATILITY"
    BASE_GEOMETRY = "BASE_GEOMETRY"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    TRADE_FEASIBILITY = "TRADE_FEASIBILITY"
    MARKET_CONTEXT = "MARKET_CONTEXT"
    CANONICAL_COMPONENT = "CANONICAL_COMPONENT"


class DirectionalExpectation(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NON_MONOTONIC = "NON_MONOTONIC"
    UNKNOWN = "UNKNOWN"


class MissingnessPolicy(StrEnum):
    PRESERVE_MISSING = "PRESERVE_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCK_ANALYSIS = "BLOCK_ANALYSIS"


class FeatureAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    CURRENT_ONLY_NOT_HISTORICAL = "CURRENT_ONLY_NOT_HISTORICAL"
    PAID_SOURCE_REQUIRED = "PAID_SOURCE_REQUIRED"
    FREE_SOURCE_POSSIBLE = "FREE_SOURCE_POSSIBLE"
    UNAVAILABLE = "UNAVAILABLE"


class FeatureQualityFlag(StrEnum):
    PASS = "PASS"
    HIGH_MISSINGNESS = "HIGH_MISSINGNESS"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    NEAR_CONSTANT = "NEAR_CONSTANT"
    OUTLIER_DOMINATED = "OUTLIER_DOMINATED"
    PARTITION_DRIFT = "PARTITION_DRIFT"
    ERA_DRIFT = "ERA_DRIFT"
    SYMBOL_CONCENTRATION = "SYMBOL_CONCENTRATION"
    DATA_NOT_POINT_IN_TIME = "DATA_NOT_POINT_IN_TIME"


class AttributionDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NON_MONOTONIC = "NON_MONOTONIC"
    NO_EVIDENCE = "NO_EVIDENCE"
    UNSTABLE = "UNSTABLE"


class StabilityClassification(StrEnum):
    STABLE_POSITIVE = "STABLE_POSITIVE"
    STABLE_NEGATIVE = "STABLE_NEGATIVE"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
    HOLDOUT_FAILURE = "HOLDOUT_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"


class FeatureConfidenceTier(StrEnum):
    A = "A_STABLE_ORTHOGONAL_HIGH_QUALITY"
    B = "B_STABLE_CONTEXT_DEPENDENT"
    C = "C_WEAK"
    D = "D_INVERSE"
    E = "E_RESEARCH_ONLY"


class RedundancyClassification(StrEnum):
    ORTHOGONAL = "ORTHOGONAL"
    PARTIALLY_REDUNDANT = "PARTIALLY_REDUNDANT"
    HIGHLY_REDUNDANT = "HIGHLY_REDUNDANT"
    SAME_SOURCE_DUPLICATE = "SAME_SOURCE_DUPLICATE"
    UNKNOWN = "UNKNOWN"


class ResearchConclusion(StrEnum):
    FEATURE_HAS_STABLE_EDGE = "FEATURE_HAS_STABLE_EDGE"
    FEATURE_IS_INVERSELY_PREDICTIVE = "FEATURE_IS_INVERSELY_PREDICTIVE"
    FEATURE_IS_REDUNDANT = "FEATURE_IS_REDUNDANT"
    FEATURE_IS_CONTEXT_DEPENDENT = "FEATURE_IS_CONTEXT_DEPENDENT"
    FEATURE_IS_UNSTABLE = "FEATURE_IS_UNSTABLE"
    FEATURE_IS_DATA_BLOCKED = "FEATURE_IS_DATA_BLOCKED"
    NO_EVIDENCE = "NO_EVIDENCE"


@dataclass(frozen=True, slots=True)
class TransactionCostPolicy:
    policy_id: str = "transaction-cost-policy-v1"
    round_trip_rate: Decimal = Decimal("0.002")
    description: str = "Configurable round-trip research cost applied to returns."

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("transaction cost policy id cannot be empty")
        if self.round_trip_rate < 0 or self.round_trip_rate >= Decimal("1"):
            raise ValueError("transaction cost rate must be between zero and one")

    @property
    def display_percent(self) -> Decimal:
        return self.round_trip_rate * Decimal("100")


@dataclass(frozen=True, slots=True)
class PartitionManifest:
    development_start: date
    development_end: date
    validation_start: date
    validation_end: date
    holdout_start: date
    holdout_end: date
    development_share: Decimal = Decimal("0.60")
    validation_share: Decimal = Decimal("0.20")
    holdout_share: Decimal = Decimal("0.20")

    def partition_for(self, observed_on: date) -> EvidencePartition:
        if observed_on <= self.development_end:
            return EvidencePartition.DEVELOPMENT
        if observed_on <= self.validation_end:
            return EvidencePartition.VALIDATION
        return EvidencePartition.HOLDOUT


@dataclass(frozen=True, slots=True)
class FeatureAttributionManifest:
    research_id: str
    generated_at: datetime
    source_commit: str
    dataset_version: str
    canonical_policy_id: str
    candidate_research_version: str
    setup_discovery_version: str
    feature_engine_version: str
    outcome_definition_version: str
    transaction_cost_policy: TransactionCostPolicy
    partition_manifest: PartitionManifest
    source_artifact_hashes: tuple[tuple[str, str], ...]
    primary_population: ResearchCohort = ResearchCohort.ALL_MARKET_OPPORTUNITIES
    primary_outcome: str = PRIMARY_OUTCOME
    secondary_outcomes: tuple[str, ...] = SECONDARY_OUTCOMES
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class ResearchPopulationRecord:
    onset_id: str
    source_onset_id: str
    event_ids: tuple[str, ...]
    symbol: str
    onset_date: date
    onset_sequence: int
    event_family: str
    candidate_status: str
    canonical_setup: str | None
    canonical_score: Decimal | None
    canonical_verdict: str | None
    canonical_gate_result: str | None
    entry_trigger: Decimal
    reference_level: Decimal
    prospective_stop: Decimal
    prospective_target: Decimal
    prospective_rr: Decimal
    confidence: Decimal
    point_in_time_inputs: tuple[tuple[str, str], ...]
    cohorts: tuple[ResearchCohort, ...]
    partition: EvidencePartition
    dataset_version: str
    feature_snapshot_hash: str


@dataclass(frozen=True, slots=True)
class ResearchPopulationSummary:
    raw_linked_onsets: int
    deduplicated_linked_onsets: int
    reconstructed_market_opportunities: int
    labelled_market_opportunities: int
    cohort_counts: tuple[tuple[str, int], ...]
    selection_bias_warning: str


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    feature_id: str
    feature_name: str
    feature_group: FeatureGroup
    definition: str
    unit: str
    lookback: int | None
    directional_expectation: DirectionalExpectation
    source_module: str
    source_lineage: tuple[str, ...]
    point_in_time_safe: bool
    missingness_policy: MissingnessPolicy
    canonical_component: str | None
    version: str
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE
    limitation: str | None = None


FeatureScalar = bool | int | float | str | None


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    onset_id: str
    symbol: str
    onset_date: date
    partition: EvidencePartition
    values: tuple[tuple[str, FeatureScalar], ...]
    source_max_date: date
    feature_snapshot_hash: str

    def value(self, feature_id: str) -> FeatureScalar:
        return dict(self.values).get(feature_id)


@dataclass(frozen=True, slots=True)
class OutcomeDefinition:
    outcome_id: str
    definition: str
    horizon: int | None
    primary: bool
    version: str = OUTCOME_DEFINITION_VERSION


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    onset_id: str
    entry_price: Decimal
    stop_price: Decimal
    plan_target_price: Decimal
    net_return_20d: Decimal | None
    net_return_60d: Decimal | None
    net_return_120d: Decimal | None
    mfe_20d: Decimal | None
    mfe_60d: Decimal | None
    mfe_120d: Decimal | None
    mae_20d: Decimal | None
    mae_60d: Decimal | None
    mae_120d: Decimal | None
    realized_r: Decimal | None
    target_1_hit: bool | None
    target_2_hit: bool | None
    plan_target_hit: bool | None
    stop_hit: bool | None
    target_before_stop: bool | None
    positive_after_costs_20d: bool | None
    positive_after_costs_60d: bool | None
    positive_after_costs_120d: bool | None
    positive_2r_before_stop: bool | None
    high_quality_winner: bool | None
    exit_reason: str
    first_event_date: date | None
    available_forward_bars: int
    transaction_cost_policy_id: str


@dataclass(frozen=True, slots=True)
class FeatureQualityRecord:
    feature_id: str
    population_count: int
    available_count: int
    missing_count: int
    missing_rate: Decimal
    unique_values: int
    zero_variance: bool
    outlier_rate: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    median: Decimal | None
    iqr: Decimal | None
    development_coverage: Decimal
    validation_coverage: Decimal
    holdout_coverage: Decimal
    flags: tuple[FeatureQualityFlag, ...]


@dataclass(frozen=True, slots=True)
class FeatureLeakageRecord:
    feature_id: str
    point_in_time_safe: bool
    maximum_source_date: date | None
    bars_after_onset: bool
    future_extrema: bool
    future_pivot_confirmation: bool
    future_normalized_percentile: bool
    full_dataset_scaling: bool
    current_mapping_used: bool
    outcome_derived: bool
    outcome_definition_coupled: bool
    status: str
    explanation: str


@dataclass(frozen=True, slots=True)
class DecileResult:
    decile: int
    sample_count: int
    winner_rate: Decimal | None
    precision: Decimal | None
    expectancy: Decimal | None


@dataclass(frozen=True, slots=True)
class AttributionResult:
    feature_id: str
    outcome_id: str
    partition: EvidencePartition | None
    horizon: int | None
    sample_count: int
    missing_count: int
    winner_median: Decimal | None
    loser_median: Decimal | None
    median_difference: Decimal | None
    standardized_effect_size: Decimal | None
    rank_biserial_correlation: Decimal | None
    auc: Decimal | None
    monotonicity_score: Decimal | None
    bootstrap_low: Decimal | None
    bootstrap_high: Decimal | None
    direction: AttributionDirection
    deciles: tuple[DecileResult, ...]


@dataclass(frozen=True, slots=True)
class ConditionalAttributionResult:
    feature_id: str
    outcome_id: str
    context_name: str
    context_value: str
    sample_count: int
    effect: Decimal | None
    auc: Decimal | None
    direction: AttributionDirection
    sign_consistent: bool | None
    simpson_paradox: bool


@dataclass(frozen=True, slots=True)
class RedundancyResult:
    feature_a: str
    feature_b: str
    sample_count: int
    pearson: Decimal | None
    spearman: Decimal | None
    mutual_information: Decimal | None
    source_lineage_jaccard: Decimal
    incremental_auc: Decimal | None
    classification: RedundancyClassification


@dataclass(frozen=True, slots=True)
class InteractionResult:
    interaction_id: str
    feature_a: str
    feature_b: str
    partition: EvidencePartition
    sample_count: int
    winner_rate: Decimal | None
    baseline_winner_rate: Decimal | None
    incremental_win_rate: Decimal | None
    stable_sign: bool
    accepted_for_research: bool
    limitation: str | None


@dataclass(frozen=True, slots=True)
class OrthogonalEdgeResult:
    feature_id: str
    model_name: str
    development_auc: Decimal | None
    validation_auc: Decimal | None
    holdout_auc: Decimal | None
    development_brier: Decimal | None
    validation_brier: Decimal | None
    holdout_brier: Decimal | None
    incremental_auc: Decimal | None
    incremental_brier_improvement: Decimal | None
    calibration_slope: Decimal | None
    feature_sign_stability: bool
    sample_count: int


@dataclass(frozen=True, slots=True)
class InformationDecayResult:
    feature_id: str
    horizon: int
    outcome_id: str
    sample_count: int
    auc: Decimal | None
    effect: Decimal | None
    direction: AttributionDirection


@dataclass(frozen=True, slots=True)
class FeatureStabilityScore:
    feature_id: str
    direction_stability: Decimal | None
    support_stability: Decimal | None
    era_stability: Decimal | None
    regime_stability: Decimal | None
    sector_stability: Decimal | None
    liquidity_stability: Decimal | None
    overall_stability: Decimal | None
    classification: StabilityClassification
    unavailable_dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureRanking:
    feature_id: str
    ranking_name: str
    rank: int
    value: Decimal | None
    confidence_tier: FeatureConfidenceTier
    conclusion: ResearchConclusion
    recommendation: str


@dataclass(frozen=True, slots=True)
class MissingInformationRecord:
    feature_id: str
    availability: FeatureAvailability
    current_source: str | None
    orthogonality_rationale: str
    priority: int | None
    limitation: str


@dataclass(frozen=True, slots=True)
class FeatureCard:
    feature_id: str
    feature_name: str
    feature_group: FeatureGroup
    direction: AttributionDirection
    confidence_tier: FeatureConfidenceTier
    development_auc: Decimal | None
    validation_auc: Decimal | None
    holdout_auc: Decimal | None
    stability_score: Decimal | None
    orthogonal_incremental_auc: Decimal | None
    information_decay: tuple[tuple[int, Decimal | None], ...]
    data_quality_flags: tuple[str, ...]
    conclusion: ResearchConclusion
    recommendation: str
    evidence_summary: str


@dataclass(frozen=True, slots=True)
class CaseStudy:
    symbol: str
    onset_id: str | None
    onset_date: date | None
    outcome: str
    canonical_result: str
    top_positive_features: tuple[tuple[str, Decimal], ...]
    top_negative_features: tuple[tuple[str, Decimal], ...]
    population_percentiles: tuple[tuple[str, Decimal], ...]
    missing_feature_groups: tuple[str, ...]
    differentiation_available_point_in_time: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class FeatureAttributionReport:
    manifest: FeatureAttributionManifest
    population: tuple[ResearchPopulationRecord, ...]
    population_summary: ResearchPopulationSummary
    feature_definitions: tuple[FeatureDefinition, ...]
    feature_snapshots: tuple[FeatureSnapshot, ...]
    outcome_definitions: tuple[OutcomeDefinition, ...]
    outcomes: tuple[OutcomeRecord, ...]
    quality: tuple[FeatureQualityRecord, ...]
    leakage: tuple[FeatureLeakageRecord, ...]
    univariate: tuple[AttributionResult, ...]
    negative_features: tuple[AttributionResult, ...]
    conditional: tuple[ConditionalAttributionResult, ...]
    redundancy: tuple[RedundancyResult, ...]
    interactions: tuple[InteractionResult, ...]
    orthogonal: tuple[OrthogonalEdgeResult, ...]
    information_decay: tuple[InformationDecayResult, ...]
    stability: tuple[FeatureStabilityScore, ...]
    rankings: tuple[FeatureRanking, ...]
    missing_information: tuple[MissingInformationRecord, ...]
    feature_cards: tuple[FeatureCard, ...]
    case_studies: tuple[CaseStudy, ...]


__all__ = [name for name in globals() if not name.startswith("_")]
