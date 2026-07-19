from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
DISCOVERY_SCHEMA_VERSION = "strategy-discovery-v1"
CURRENT_PRODUCTION_POLICY = "APPROVAL_POLICY_V1"


class HistoricalTruthClass(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    RECONSTRUCTED = "RECONSTRUCTED"
    INSUFFICIENT = "INSUFFICIENT"


class FeatureValidity(StrEnum):
    VALID = "VALID"
    QUARANTINED = "QUARANTINED"
    INVALID = "INVALID"


class MissingValueTreatment(StrEnum):
    EXCLUDE_CONDITION = "EXCLUDE_CONDITION"
    EXPLICIT_CATEGORY = "EXPLICIT_CATEGORY"
    FALSE = "FALSE"
    REJECT_ROW = "REJECT_ROW"


class StrategyFamily(StrEnum):
    SCORE_THRESHOLD = "SCORE_THRESHOLD"
    PRICE_STRUCTURE = "PRICE_STRUCTURE"
    PRICE_VOLUME = "PRICE_VOLUME"
    SETUP_SPECIFIC = "SETUP_SPECIFIC"
    ENTRY_TIMING = "ENTRY_TIMING"
    TRADE_PLAN_QUALITY = "TRADE_PLAN_QUALITY"
    SIGNAL_COMPONENT_SUBSET = "SIGNAL_COMPONENT_SUBSET"
    APPROVAL_GATE_SUBSET = "APPROVAL_GATE_SUBSET"
    SIMPLE_CONJUNCTION = "SIMPLE_CONJUNCTION"
    APPROVAL_POLICY_V1 = "APPROVAL_POLICY_V1"
    RAW_RECORDED_APPROVAL = "RAW_RECORDED_APPROVAL"
    NO_TRADE = "NO_TRADE"


class ConditionOperator(StrEnum):
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    EQUAL = "EQUAL"
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"


class GeneralisationClassification(StrEnum):
    INVALID_DATA = "INVALID_DATA"
    LEAKAGE_RISK = "LEAKAGE_RISK"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    OVERFIT = "OVERFIT"
    UNSTABLE = "UNSTABLE"
    NEGATIVE_EXPECTANCY = "NEGATIVE_EXPECTANCY"
    NO_MATERIAL_EDGE = "NO_MATERIAL_EDGE"
    ROBUST_BUT_LOW_CAPACITY = "ROBUST_BUT_LOW_CAPACITY"
    SHADOW_VALIDATION_CANDIDATE = "SHADOW_VALIDATION_CANDIDATE"


class EvaluationStage(StrEnum):
    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class FinalStrategyDecision(StrEnum):
    NO_GENERALISABLE_STRATEGY_FOUND = "NO_GENERALISABLE_STRATEGY_FOUND"


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    source: str
    timestamp_semantics: str
    unit: str
    missing_value_treatment: MissingValueTreatment
    available_at_decision_time: bool
    validity: FeatureValidity
    quarantine_reason: str | None
    same_source_group: str | None
    known_lineage_overlap: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.source.strip():
            raise ValueError("feature name and source are required")
        if self.validity is FeatureValidity.QUARANTINED and not self.quarantine_reason:
            raise ValueError("quarantined feature requires a reason")

    @property
    def usable_for_discovery(self) -> bool:
        return (
            self.available_at_decision_time and self.validity is FeatureValidity.VALID
        )


@dataclass(frozen=True, slots=True)
class DiscoveryExclusion:
    candidate_id: str
    symbol: str
    reason_code: str
    explanation: str


@dataclass(frozen=True, slots=True)
class DiscoveryRow:
    candidate_id: str
    candidate_timestamp: datetime
    symbol: str
    series: str | None
    identity_status: str
    feature_timestamp: datetime
    recommendation: str
    setup: str | None
    entry_timing_state: str
    approval_gate_states: dict[str, bool]
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    confirmation_entry: Decimal | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    outcome_horizon: str
    realised_outcome: str
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    realised_return_pct: Decimal | None
    realised_r_multiple: Decimal | None
    evidence_provenance: dict[str, str]
    replay_version: str
    data_quality_status: str
    corporate_action_status: str
    truth_class: HistoricalTruthClass
    features: dict[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_timestamp", _utc(self.candidate_timestamp))
        object.__setattr__(self, "feature_timestamp", _utc(self.feature_timestamp))
        if self.feature_timestamp > self.candidate_timestamp:
            raise ValueError("feature timestamp cannot follow candidate timestamp")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "approval_gate_states",
            MappingProxyType(dict(sorted(self.approval_gate_states.items()))),
        )
        object.__setattr__(
            self,
            "evidence_provenance",
            MappingProxyType(dict(sorted(self.evidence_provenance.items()))),
        )
        object.__setattr__(
            self,
            "features",
            MappingProxyType(dict(sorted(self.features.items()))),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_timestamp": self.candidate_timestamp.isoformat(),
            "symbol": self.symbol,
            "series": self.series,
            "identity_status": self.identity_status,
            "feature_timestamp": self.feature_timestamp.isoformat(),
            "recommendation": self.recommendation,
            "setup": self.setup,
            "entry_timing_state": self.entry_timing_state,
            "approval_gate_states": dict(self.approval_gate_states),
            "entry_zone_low": _text(self.entry_zone_low),
            "entry_zone_high": _text(self.entry_zone_high),
            "confirmation_entry": _text(self.confirmation_entry),
            "stop_loss": _text(self.stop_loss),
            "target_1": _text(self.target_1),
            "target_2": _text(self.target_2),
            "target_3": _text(self.target_3),
            "outcome_horizon": self.outcome_horizon,
            "realised_outcome": self.realised_outcome,
            "mfe_pct": _text(self.mfe_pct),
            "mae_pct": _text(self.mae_pct),
            "realised_return_pct": _text(self.realised_return_pct),
            "realised_r_multiple": _text(self.realised_r_multiple),
            "evidence_provenance": dict(self.evidence_provenance),
            "replay_version": self.replay_version,
            "data_quality_status": self.data_quality_status,
            "corporate_action_status": self.corporate_action_status,
            "truth_class": self.truth_class.value,
            "features": dict(self.features),
        }


@dataclass(frozen=True, slots=True)
class DiscoveryDataset:
    dataset_version: str
    generated_at: datetime
    source: str
    source_hash: str
    population_class: HistoricalTruthClass
    rows: tuple[DiscoveryRow, ...]
    exclusions: tuple[DiscoveryExclusion, ...]
    quarantined_population: int
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        if self.production_influence:
            raise ValueError("discovery dataset cannot influence production")
        if any(row.truth_class is not self.population_class for row in self.rows):
            raise ValueError("discovery dataset cannot mix historical truth classes")

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class StrategyCondition:
    feature_name: str
    operator: ConditionOperator
    value: str

    @property
    def canonical_key(self) -> str:
        return f"{self.feature_name}|{self.operator.value}|{self.value}"


@dataclass(frozen=True, slots=True)
class StrategySpecification:
    strategy_version: str
    strategy_hash: str
    name: str
    family: StrategyFamily
    conditions: tuple[StrategyCondition, ...]
    benchmark: bool = False
    description: str = ""
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("research strategy cannot influence production")
        if not self.strategy_version.startswith("STRATEGY_RESEARCH_V"):
            raise ValueError("invalid strategy research version")
        canonical = tuple(sorted(self.conditions, key=lambda item: item.canonical_key))
        object.__setattr__(self, "conditions", canonical)


@dataclass(frozen=True, slots=True)
class SearchSpaceManifest:
    manifest_version: str
    maximum_conditions_per_strategy: int
    maximum_variants_per_family: int
    family_variant_counts: dict[str, int]
    total_variants: int
    search_space_hash: str
    feature_manifest_hash: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "family_variant_counts",
            MappingProxyType(dict(sorted(self.family_variant_counts.items()))),
        )


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    training_start: date
    training_end: date
    validation_start: date
    validation_end: date
    purge_gap_days: int
    training_candidate_ids: tuple[str, ...]
    validation_candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.training_end >= self.validation_start:
            raise ValueError("training must end before validation starts")
        if set(self.training_candidate_ids) & set(self.validation_candidate_ids):
            raise ValueError("walk-forward populations overlap")


@dataclass(frozen=True, slots=True)
class EvaluationCosts:
    transaction_cost_bps: Decimal
    slippage_bps: Decimal
    version: str
    rationale: str
    research_assumption: bool = True

    @property
    def round_trip_cost_pct(self) -> Decimal:
        return (self.transaction_cost_bps + self.slippage_bps) / Decimal("100")


@dataclass(frozen=True, slots=True)
class EvidenceConstraints:
    minimum_total_completed_trades: int
    minimum_completed_trades_per_fold: int
    minimum_positive_expectancy_folds: int
    maximum_drawdown_pct: Decimal
    maximum_winner_concentration_pct: Decimal
    maximum_validation_degradation_pct: Decimal
    version: str
    rationale: str
    research_assumption: bool = True


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    population_count: int
    completed_trades: int
    approval_rate_pct: Decimal | None
    precision_pct: Decimal | None
    precision_ci_low_pct: Decimal | None
    precision_ci_high_pct: Decimal | None
    recall_pct: Decimal | None
    average_winner_pct: Decimal | None
    average_loser_pct: Decimal | None
    payoff_ratio: Decimal | None
    expectancy_pct: Decimal | None
    profit_factor: Decimal | None
    average_r_multiple: Decimal | None
    maximum_drawdown_pct: Decimal | None
    downside_deviation_pct: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    consecutive_losses: int
    capital_utilisation_pct: Decimal | None
    turnover: int
    average_holding_period_days: Decimal | None
    largest_winner_contribution_pct: Decimal | None
    gross_expectancy_pct: Decimal | None
    round_trip_cost_pct: Decimal


@dataclass(frozen=True, slots=True)
class FoldEvaluation:
    fold_id: str
    strategy_version: str
    stage: EvaluationStage
    metrics: StrategyMetrics


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    strategy: StrategySpecification
    training_metrics: StrategyMetrics
    validation_metrics: StrategyMetrics
    holdout_metrics: StrategyMetrics | None
    fold_evaluations: tuple[FoldEvaluation, ...]
    selected_for_holdout: bool
    holdout_access_id: str | None


@dataclass(frozen=True, slots=True)
class RobustnessResult:
    strategy_version: str
    parameter_perturbation_passed: bool
    feature_ablation_passed: bool
    cost_stress_passed: bool
    delayed_entry_status: str
    missed_fill_passed: bool
    stop_gap_status: str
    bootstrap_expectancy_low_pct: Decimal | None
    bootstrap_expectancy_high_pct: Decimal | None
    fold_consistency_pct: Decimal | None
    symbol_concentration_pct: Decimal | None
    setup_concentration_pct: Decimal | None
    winner_concentration_pct: Decimal | None
    weaknesses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MultipleTestingResult:
    strategy_version: str
    raw_p_value: Decimal | None
    adjusted_p_value: Decimal | None
    hypotheses_tested: int
    adjustment_method: str
    statistically_significant: bool


@dataclass(frozen=True, slots=True)
class StrategyLeaderboardEntry:
    rank: int
    strategy: StrategySpecification
    evaluation: StrategyEvaluation
    robustness: RobustnessResult
    multiple_testing: MultipleTestingResult
    classification: GeneralisationClassification
    classification_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShadowStrategyCandidate:
    cohort_version: str
    strategy: StrategySpecification
    published_at: datetime
    recommendation_engine_version: str
    source_dataset_version: str
    immutable_specification_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class StrategyDiscoveryReport:
    generated_at: datetime
    dataset: DiscoveryDataset
    feature_manifest: tuple[FeatureDefinition, ...]
    search_manifest: SearchSpaceManifest
    folds: tuple[WalkForwardFold, ...]
    leaderboard: tuple[StrategyLeaderboardEntry, ...]
    benchmark_entries: tuple[StrategyLeaderboardEntry, ...]
    decision: str
    dominant_failure_reasons: tuple[str, ...]
    highest_value_evidence_gap: str
    current_forward_evidence: str
    shadow_candidate: ShadowStrategyCandidate | None = None
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class HoldoutAccessRecord:
    access_id: str
    accessed_at: datetime
    dataset_version: str
    strategy_versions: tuple[str, ...]
    purpose: str
    result_hash: str


@dataclass(frozen=True, slots=True)
class DiscoveryRunConfig:
    maximum_conditions_per_strategy: int = 3
    maximum_variants_per_family: int = 25
    purge_gap_days: int = 20
    holdout_fraction_pct: int = 20
    validation_fraction_pct: int = 20
    costs: EvaluationCosts = field(
        default_factory=lambda: EvaluationCosts(
            transaction_cost_bps=Decimal("20"),
            slippage_bps=Decimal("10"),
            version="research-cost-assumption-v1",
            rationale=(
                "Explicit initial research assumption; replace with measured execution "
                "costs before deployment decisions."
            ),
        )
    )
    constraints: EvidenceConstraints = field(
        default_factory=lambda: EvidenceConstraints(
            minimum_total_completed_trades=30,
            minimum_completed_trades_per_fold=10,
            minimum_positive_expectancy_folds=2,
            maximum_drawdown_pct=Decimal("25"),
            maximum_winner_concentration_pct=Decimal("40"),
            maximum_validation_degradation_pct=Decimal("50"),
            version="research-evidence-constraints-v1",
            rationale=(
                "Explicit conservative research assumptions; not production thresholds."
            ),
        )
    )


def decimal_feature(features: dict[str, str] | Any, name: str) -> Decimal | None:
    value = features.get(name)
    if value is None or value in {"", "unavailable", "None"}:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CURRENT_PRODUCTION_POLICY",
    "ConditionOperator",
    "DISCOVERY_SCHEMA_VERSION",
    "DiscoveryDataset",
    "DiscoveryExclusion",
    "DiscoveryRow",
    "DiscoveryRunConfig",
    "EvaluationCosts",
    "EvaluationStage",
    "EvidenceConstraints",
    "FeatureDefinition",
    "FeatureValidity",
    "FinalStrategyDecision",
    "FoldEvaluation",
    "GeneralisationClassification",
    "HistoricalTruthClass",
    "HoldoutAccessRecord",
    "MissingValueTreatment",
    "MultipleTestingResult",
    "PRODUCTION_INFLUENCE",
    "RobustnessResult",
    "SearchSpaceManifest",
    "ShadowStrategyCandidate",
    "StrategyCondition",
    "StrategyDiscoveryReport",
    "StrategyEvaluation",
    "StrategyFamily",
    "StrategyLeaderboardEntry",
    "StrategyMetrics",
    "StrategySpecification",
    "WalkForwardFold",
    "decimal_feature",
]
