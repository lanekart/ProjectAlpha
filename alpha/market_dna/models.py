from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
MARKET_DNA_SCHEMA_VERSION = "market-dna-v1.2"


class DNAEvidenceClass(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    RECONSTRUCTED = "RECONSTRUCTED"
    PROVISIONAL = "PROVISIONAL"
    FORWARD_OBSERVED = "FORWARD_OBSERVED"


class FeatureKind(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    CATEGORICAL = "CATEGORICAL"
    ORDINAL = "ORDINAL"
    BOOLEAN = "BOOLEAN"


class FeatureQuality(StrEnum):
    USABLE = "USABLE"
    USABLE_WITH_CAUTION = "USABLE_WITH_CAUTION"
    LINEAGE_CONFOUNDED = "LINEAGE_CONFOUNDED"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    LEAKAGE_RISK = "LEAKAGE_RISK"
    QUARANTINED = "QUARANTINED"


class ConditionOperator(StrEnum):
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    EQUAL = "EQUAL"
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"


class PatternDirection(StrEnum):
    ENRICHED = "ENRICHED"
    DEPLETED = "DEPLETED"


class TemporalStability(StrEnum):
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    EMERGING = "EMERGING"
    REGIME_DEPENDENT = "REGIME_DEPENDENT"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DNAPatternStatus(StrEnum):
    INVALID_DATA = "INVALID_DATA"
    LEAKAGE_RISK = "LEAKAGE_RISK"
    LINEAGE_CONFOUNDED = "LINEAGE_CONFOUNDED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    MULTIPLE_TESTING_FAILURE = "MULTIPLE_TESTING_FAILURE"
    CONCENTRATED = "CONCENTRATED"
    UNSTABLE = "UNSTABLE"
    RECONSTRUCTED_RESEARCH_ONLY = "RECONSTRUCTED_RESEARCH_ONLY"
    ROBUST_RESEARCH_PATTERN = "ROBUST_RESEARCH_PATTERN"
    STRATEGY_HYPOTHESIS_CANDIDATE = "STRATEGY_HYPOTHESIS_CANDIDATE"


class MarketDNAConclusion(StrEnum):
    NO_ROBUST_MARKET_DNA_FOUND = "NO_ROBUST_MARKET_DNA_FOUND"
    ROBUST_RESEARCH_PATTERNS_FOUND_NO_STRATEGY_HYPOTHESES = (
        "ROBUST_RESEARCH_PATTERNS_FOUND_NO_STRATEGY_HYPOTHESES"
    )


@dataclass(frozen=True, slots=True)
class OutcomeCohortDefinition:
    cohort_id: str
    title: str
    predicate: str
    horizon: str
    cost_profile_id: str
    version: str
    description: str

    def __post_init__(self) -> None:
        if not self.cohort_id or not self.predicate or not self.version:
            raise ValueError("cohort identity, predicate, and version are required")


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    feature_id: str
    name: str
    kind: FeatureKind
    unit: str
    valid_range: str
    timestamp_semantics: str
    missing_value_treatment: str
    provenance: str
    evidence_class: DNAEvidenceClass
    threshold_grid: tuple[Decimal, ...]
    lineage_overlaps: tuple[str, ...]
    known_defects: tuple[str, ...]
    base_quality: FeatureQuality
    permitted_with_caution: bool = False

    @property
    def discovery_permitted(self) -> bool:
        return self.base_quality is FeatureQuality.USABLE or (
            self.base_quality is FeatureQuality.USABLE_WITH_CAUTION
            and self.permitted_with_caution
        )


@dataclass(frozen=True, slots=True)
class FeatureAudit:
    feature: FeatureDefinition
    quality: FeatureQuality
    population_count: int
    available_count: int
    missing_count: int
    missing_pct: Decimal
    distinct_values: int
    scale_valid: bool
    point_in_time_valid: bool
    reasons: tuple[str, ...]

    @property
    def discovery_permitted(self) -> bool:
        return self.quality is FeatureQuality.USABLE or (
            self.quality is FeatureQuality.USABLE_WITH_CAUTION
            and self.feature.permitted_with_caution
        )


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    candidate_id: str
    candidate_timestamp: datetime
    feature_timestamp: datetime
    symbol: str
    setup: str
    horizon: str
    evidence_class: DNAEvidenceClass
    corporate_action_status: str
    feature_values: Mapping[str, str]
    realised_outcome: str
    gross_return_pct: Decimal
    net_return_pct: Decimal
    realised_r_multiple: Decimal | None
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    target_1_touched: bool | None
    stop_touched: bool | None
    raw_approved: bool
    entry_missed_proxy: bool
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        candidate_time = _utc(self.candidate_timestamp)
        feature_time = _utc(self.feature_timestamp)
        if feature_time > candidate_time:
            raise ValueError("feature snapshot follows the decision timestamp")
        if self.production_influence:
            raise ValueError("Market DNA snapshots cannot influence production")
        object.__setattr__(self, "candidate_timestamp", candidate_time)
        object.__setattr__(self, "feature_timestamp", feature_time)
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "feature_values",
            MappingProxyType(dict(sorted(self.feature_values.items()))),
        )


@dataclass(frozen=True, slots=True)
class CohortSummary:
    definition: OutcomeCohortDefinition
    candidate_ids: tuple[str, ...]
    sample_size: int
    start_date: date | None
    end_date: date | None
    symbol_count: int
    evidence_class: DNAEvidenceClass
    corporate_action_status: str
    reconstruction_status: str
    average_net_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class FeatureCondition:
    feature_id: str
    operator: ConditionOperator
    value: str

    @property
    def canonical_key(self) -> str:
        return f"{self.feature_id}|{self.operator.value}|{self.value}"


@dataclass(frozen=True, slots=True)
class DistributionComparison:
    cohort_id: str
    scope: str
    feature_id: str
    cohort_count: int
    baseline_count: int
    cohort_mean: Decimal | None
    baseline_mean: Decimal | None
    cohort_median: Decimal | None
    baseline_median: Decimal | None
    standardised_effect_size: Decimal | None
    distribution_overlap: Decimal | None
    raw_p_value: Decimal | None


@dataclass(frozen=True, slots=True)
class FeatureFinding:
    finding_id: str
    cohort_id: str
    scope: str
    condition: FeatureCondition
    cohort_count: int
    baseline_count: int
    cohort_match_count: int
    baseline_match_count: int
    cohort_prevalence_pct: Decimal | None
    baseline_prevalence_pct: Decimal | None
    enrichment_ratio: Decimal | None
    odds_ratio: Decimal | None
    risk_ratio: Decimal | None
    effect_size: Decimal | None
    confidence_interval_low: Decimal | None
    confidence_interval_high: Decimal | None
    raw_p_value: Decimal | None
    adjusted_p_value: Decimal | None
    direction: PatternDirection
    fold_consistency_pct: Decimal | None
    years_represented: int
    symbols_represented: int
    symbol_concentration_pct: Decimal | None
    period_concentration_pct: Decimal | None
    winner_concentration_pct: Decimal | None
    temporal_stability: TemporalStability
    evidence_class: DNAEvidenceClass
    lineage_risks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchedCohortResult:
    cohort_id: str
    cohort_candidates: int
    matched_pairs: int
    unmatched_cohort: int
    unmatched_baseline: int
    matching_dimensions: tuple[str, ...]
    limitations: tuple[str, ...]
    matched_candidate_ids: tuple[str, ...]
    matched_baseline_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InteractionFinding:
    interaction_id: str
    cohort_id: str
    conditions: tuple[FeatureCondition, ...]
    sample_size: int
    baseline_size: int
    enrichment_ratio: Decimal | None
    effect_size: Decimal | None
    raw_p_value: Decimal | None
    adjusted_p_value: Decimal | None
    fold_consistency_pct: Decimal | None
    symbol_concentration_pct: Decimal | None
    lineage_penalty: bool
    status: DNAPatternStatus


@dataclass(frozen=True, slots=True)
class ClusterResult:
    cluster_id: str
    sample_size: int
    profile: tuple[str, ...]
    average_net_return_pct: Decimal | None
    winner_rate_pct: Decimal | None
    dominant_symbol: str | None
    dominant_setup: str | None
    stability_pct: Decimal | None
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HierarchicalResult:
    scope: str
    population: int
    strongest_finding_id: str | None
    strongest_enrichment_ratio: Decimal | None
    generalises_outside_subgroup: bool | None
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DNAPattern:
    pattern_id: str
    version: str
    title: str
    outcome_cohort: str
    scope: str
    feature_conditions: tuple[FeatureCondition, ...]
    direction: PatternDirection
    enrichment_ratio: Decimal | None
    effect_size: Decimal | None
    confidence_interval_low: Decimal | None
    confidence_interval_high: Decimal | None
    adjusted_p_value: Decimal | None
    sample_size: int
    years_represented: int
    symbols_represented: int
    fold_stability_pct: Decimal | None
    symbol_concentration_pct: Decimal | None
    period_concentration_pct: Decimal | None
    winner_concentration_pct: Decimal | None
    evidence_class: DNAEvidenceClass
    lineage_risks: tuple[str, ...]
    robustness_classification: TemporalStability
    status: DNAPatternStatus
    hypothesis_text: str
    rejection_reasons: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DNA patterns cannot influence production")
        object.__setattr__(
            self,
            "feature_conditions",
            tuple(sorted(self.feature_conditions, key=lambda item: item.canonical_key)),
        )


@dataclass(frozen=True, slots=True)
class DNAHypothesis:
    hypothesis_id: str
    originating_pattern_ids: tuple[str, ...]
    canonical_conditions: tuple[FeatureCondition, ...]
    proposed_entry_logic: str
    avoid_conditions: tuple[FeatureCondition, ...]
    proposed_horizon: str
    expected_mechanism: str
    sample_evidence: str
    limitations: tuple[str, ...]
    required_strategy_lab_test: str
    required_walk_forward_test: str
    evidence_class: DNAEvidenceClass
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DNA hypotheses cannot influence production")


@dataclass(frozen=True, slots=True)
class MultipleTestingSummary:
    hypotheses_tested: int
    effective_hypotheses: int
    procedure: str
    significance_threshold: Decimal
    surviving_findings: int
    rejected_findings: int


@dataclass(frozen=True, slots=True)
class DNAMatchResult:
    pattern_id: str
    candidate_id: str
    matched_conditions: tuple[str, ...]
    unmatched_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    pattern_support: int
    evidence_quality: str
    cohort_similarity_pct: Decimal | None
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DNA matching cannot influence production")


@dataclass(frozen=True, slots=True)
class StrategyLabHypothesisSpecification:
    specification_id: str
    hypothesis_id: str
    originating_pattern_ids: tuple[str, ...]
    conditions: tuple[FeatureCondition, ...]
    entry_logic: str
    horizon: str
    evidence_class: DNAEvidenceClass
    assumptions: tuple[str, ...]
    execute_automatically: bool = False
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.execute_automatically or self.production_influence:
            raise ValueError(
                "published DNA hypotheses must remain inert research specs"
            )


@dataclass(frozen=True, slots=True)
class DNADiscoveryReport:
    report_id: str
    generated_at: datetime
    dataset_version: str
    evidence_class: DNAEvidenceClass
    source_rows: int
    excluded_rows: int
    feature_audits: tuple[FeatureAudit, ...]
    cohorts: tuple[CohortSummary, ...]
    matched_cohorts: tuple[MatchedCohortResult, ...]
    distributions: tuple[DistributionComparison, ...]
    findings: tuple[FeatureFinding, ...]
    interactions: tuple[InteractionFinding, ...]
    clusters: tuple[ClusterResult, ...]
    hierarchy: tuple[HierarchicalResult, ...]
    patterns: tuple[DNAPattern, ...]
    hypotheses: tuple[DNAHypothesis, ...]
    multiple_testing: MultipleTestingSummary
    final_conclusion: str
    highest_value_evidence_gap: str
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        if self.production_influence:
            raise ValueError("Market DNA reports cannot influence production")
        allowed = {item.value for item in MarketDNAConclusion}
        if not (
            self.final_conclusion in allowed
            or self.final_conclusion.startswith("PUBLISH_DNA_HYPOTHESIS_")
        ):
            raise ValueError("invalid Market DNA final conclusion")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "MARKET_DNA_SCHEMA_VERSION",
    "PRODUCTION_INFLUENCE",
    "ClusterResult",
    "CohortSummary",
    "ConditionOperator",
    "DNADiscoveryReport",
    "DNAEvidenceClass",
    "DNAHypothesis",
    "DNAMatchResult",
    "DNAPattern",
    "DNAPatternStatus",
    "DistributionComparison",
    "FeatureAudit",
    "FeatureCondition",
    "FeatureDefinition",
    "FeatureFinding",
    "FeatureKind",
    "FeatureQuality",
    "FeatureSnapshot",
    "HierarchicalResult",
    "InteractionFinding",
    "MarketDNAConclusion",
    "MatchedCohortResult",
    "MultipleTestingSummary",
    "OutcomeCohortDefinition",
    "PatternDirection",
    "StrategyLabHypothesisSpecification",
    "TemporalStability",
]
