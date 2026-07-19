from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
AUTOMATIC_DEPLOYMENT = False
AUTOMATIC_WEIGHT_MUTATION = False
CANONICAL_WEIGHTS_IMMUTABLE = True
HOLDOUT_REQUIRED = True
FORWARD_VALIDATION_REQUIRED = True
OVERLAP_PENALTY_REQUIRED = True
POLICY_VERSIONING_REQUIRED = True
ADAPTIVE_WEIGHT_SCHEMA_VERSION = "adaptive-indicator-weights-v1.0"
ADAPTIVE_WEIGHT_METHOD_VERSION = "bounded-contribution-v1.0"


class AlphaComponent(StrEnum):
    PRICE_STRUCTURE = "price_structure"
    VOLUME = "volume"
    TREND = "trend"
    RELATIVE_STRENGTH = "relative_strength"
    RETRACEMENT = "retracement"
    CANDLESTICK = "candlestick"
    BREAKOUT_SETUP = "breakout_setup"
    MARKET_REGIME = "market_regime"
    SECTOR = "sector"
    RISK_VOLATILITY = "risk_volatility"


CANONICAL_COMPONENT_WEIGHTS: tuple[tuple[AlphaComponent, Decimal], ...] = (
    (AlphaComponent.PRICE_STRUCTURE, Decimal("20")),
    (AlphaComponent.VOLUME, Decimal("17")),
    (AlphaComponent.TREND, Decimal("15")),
    (AlphaComponent.RELATIVE_STRENGTH, Decimal("13")),
    (AlphaComponent.RETRACEMENT, Decimal("10")),
    (AlphaComponent.CANDLESTICK, Decimal("8")),
    (AlphaComponent.BREAKOUT_SETUP, Decimal("7")),
    (AlphaComponent.MARKET_REGIME, Decimal("5")),
    (AlphaComponent.SECTOR, Decimal("3")),
    (AlphaComponent.RISK_VOLATILITY, Decimal("2")),
)
_COMPONENT_ORDER = {component: index for index, component in enumerate(AlphaComponent)}


class WeightLayer(StrEnum):
    CANONICAL_WEIGHTS = "CANONICAL_WEIGHTS"
    RESEARCH_PROPOSED_WEIGHTS = "RESEARCH_PROPOSED_WEIGHTS"
    DEPLOYED_WEIGHTS = "DEPLOYED_WEIGHTS"


class EvidencePartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"
    FORWARD_OBSERVED = "FORWARD_OBSERVED"


class EvidenceQuality(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class AblationRole(StrEnum):
    WITH_COMPONENT = "WITH_COMPONENT"
    WITHOUT_COMPONENT = "WITHOUT_COMPONENT"


class RedundancyClass(StrEnum):
    UNIQUE = "UNIQUE"
    PARTIALLY_REDUNDANT = "PARTIALLY_REDUNDANT"
    HIGHLY_REDUNDANT = "HIGHLY_REDUNDANT"
    SAME_SOURCE = "SAME_SOURCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class StabilityClass(StrEnum):
    ROBUST = "ROBUST"
    MODERATELY_STABLE = "MODERATELY_STABLE"
    CONDITIONAL = "CONDITIONAL"
    UNSTABLE = "UNSTABLE"
    NEGATIVE = "NEGATIVE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ContributionConfidence(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class ComponentDecisionState(StrEnum):
    INCREASE_WEIGHT = "INCREASE_WEIGHT"
    MAINTAIN_WEIGHT = "MAINTAIN_WEIGHT"
    DECREASE_WEIGHT = "DECREASE_WEIGHT"
    CONDITIONAL_WEIGHT = "CONDITIONAL_WEIGHT"
    DISABLE_CANDIDATE = "DISABLE_CANDIDATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class HierarchyLevel(StrEnum):
    SETUP_REGIME = "SETUP_REGIME"
    SETUP = "SETUP"
    REGIME = "REGIME"
    HORIZON = "HORIZON"
    UNIVERSAL_ADAPTIVE = "UNIVERSAL_ADAPTIVE"
    CANONICAL = "CANONICAL"


class CandidatePolicyState(StrEnum):
    DRAFT = "DRAFT"
    DEVELOPMENT_PASS = "DEVELOPMENT_PASS"
    VALIDATION_PASS = "VALIDATION_PASS"
    HOLDOUT_PASS = "HOLDOUT_PASS"
    FORWARD_OBSERVATION = "FORWARD_OBSERVATION"
    PROMOTE_TO_POLICY_REVIEW = "PROMOTE_TO_POLICY_REVIEW"
    REJECTED = "REJECTED"


class PromotionDecision(StrEnum):
    PROMOTE_TO_POLICY_REVIEW = "PROMOTE_TO_POLICY_REVIEW"
    REJECT = "REJECT"
    MORE_EVIDENCE = "MORE_EVIDENCE"
    CONDITIONAL_ONLY = "CONDITIONAL_ONLY"


@dataclass(frozen=True, slots=True)
class ComponentWeight:
    component: AlphaComponent
    weight: Decimal

    def __post_init__(self) -> None:
        if self.weight < Decimal("0"):
            raise ValueError("component weight cannot be negative")


@dataclass(frozen=True, slots=True)
class WeightSet:
    layer: WeightLayer
    policy_id: str
    weights: tuple[ComponentWeight, ...]

    def __post_init__(self) -> None:
        expected = set(AlphaComponent)
        supplied = {item.component for item in self.weights}
        if supplied != expected or len(self.weights) != len(expected):
            raise ValueError(
                "weight set must contain each Alpha component exactly once"
            )
        total = sum((item.weight for item in self.weights), start=Decimal("0"))
        if abs(total - Decimal("100")) > Decimal("0.0001"):
            raise ValueError("component weights must normalize to 100")
        if not self.policy_id.strip():
            raise ValueError("policy_id is required")
        object.__setattr__(
            self,
            "weights",
            tuple(
                sorted(self.weights, key=lambda item: _COMPONENT_ORDER[item.component])
            ),
        )

    def for_component(self, component: AlphaComponent) -> Decimal:
        return next(item.weight for item in self.weights if item.component is component)


def canonical_weight_set() -> WeightSet:
    return WeightSet(
        layer=WeightLayer.CANONICAL_WEIGHTS,
        policy_id="ALPHA_CANONICAL",
        weights=tuple(
            ComponentWeight(component, weight)
            for component, weight in CANONICAL_COMPONENT_WEIGHTS
        ),
    )


def deployed_weight_set() -> WeightSet:
    return WeightSet(
        layer=WeightLayer.DEPLOYED_WEIGHTS,
        policy_id="ALPHA_DEPLOYED_CURRENT",
        weights=tuple(
            ComponentWeight(component, weight)
            for component, weight in CANONICAL_COMPONENT_WEIGHTS
        ),
    )


@dataclass(frozen=True, slots=True)
class ComponentScore:
    component: AlphaComponent
    score: Decimal | None
    available: bool
    source_lineage: str

    def __post_init__(self) -> None:
        if self.available and self.score is None:
            raise ValueError("available component score requires a value")
        if self.score is not None and not Decimal("0") <= self.score <= Decimal("1"):
            raise ValueError("component scores must be normalized to [0, 1]")
        if not self.source_lineage.strip():
            raise ValueError("component source lineage is required")


@dataclass(frozen=True, slots=True)
class CompletedOutcomeEvidence:
    recommendation_id: str
    candidate_id: str | None
    symbol: str
    exchange: str
    decision_date: date
    setup_family: str
    strategy_family: str
    market_regime: str
    sector: str
    holding_horizon: str
    component_scores: tuple[ComponentScore, ...]
    canonical_weights: WeightSet
    entry: Decimal
    stop: Decimal
    exit: Decimal
    realized_return: Decimal
    realized_r_multiple: Decimal
    winner: bool
    transaction_costs: Decimal
    dataset_version: str
    policy_version: str
    provenance: str
    partition: EvidencePartition
    approved: bool
    stop_policy: str
    exit_policy: str
    exit_date: date | None = None
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("adaptive-weight evidence cannot influence production")
        required = (
            self.recommendation_id,
            self.symbol,
            self.exchange,
            self.setup_family,
            self.strategy_family,
            self.holding_horizon,
            self.dataset_version,
            self.policy_version,
            self.provenance,
            self.stop_policy,
            self.exit_policy,
        )
        if any(not item.strip() for item in required):
            raise ValueError(
                "completed outcome evidence requires complete identity and lineage"
            )
        if self.entry <= Decimal("0") or self.exit <= Decimal("0"):
            raise ValueError("completed outcome prices must be positive")
        if self.stop < Decimal("0") or self.transaction_costs < Decimal("0"):
            raise ValueError("stop and costs cannot be negative")
        supplied = {item.component for item in self.component_scores}
        if supplied != set(AlphaComponent):
            raise ValueError("evidence must retain availability for every component")
        if self.canonical_weights.layer is not WeightLayer.CANONICAL_WEIGHTS:
            raise ValueError("evidence must retain the immutable canonical baseline")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        object.__setattr__(
            self,
            "component_scores",
            tuple(
                sorted(
                    self.component_scores,
                    key=lambda item: _COMPONENT_ORDER[item.component],
                )
            ),
        )

    def score_for(self, component: AlphaComponent) -> Decimal | None:
        item = next(
            score for score in self.component_scores if score.component is component
        )
        return item.score if item.available else None

    def lineage_for(self, component: AlphaComponent) -> str:
        return next(
            score.source_lineage
            for score in self.component_scores
            if score.component is component
        )

    @property
    def component_availability(self) -> MappingProxyType[str, bool]:
        return MappingProxyType(
            {item.component.value: item.available for item in self.component_scores}
        )


@dataclass(frozen=True, slots=True)
class ResearchPerformance:
    expectancy: Decimal
    win_rate: Decimal
    average_winner_r: Decimal
    average_loser_r: Decimal
    profit_factor: Decimal | None
    max_drawdown: Decimal
    trade_count: int
    average_holding_period: Decimal
    turnover: Decimal | None
    transaction_costs: Decimal | None
    sector_concentration: Decimal
    setup_concentration: Decimal

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise ValueError("trade_count cannot be negative")


@dataclass(frozen=True, slots=True)
class AblationObservation:
    research_id: str
    component: AlphaComponent
    role: AblationRole
    symbol: str
    decision_date: date
    strategy_family: str
    setup_family: str
    stop_policy: str
    exit_policy: str
    cost_profile: str
    dataset_version: str
    partition: EvidencePartition
    performance: ResearchPerformance

    @property
    def match_key(self) -> tuple[str, ...]:
        return (
            self.symbol.upper(),
            self.decision_date.isoformat(),
            self.strategy_family,
            self.setup_family,
            self.stop_policy,
            self.exit_policy,
            self.cost_profile,
            self.dataset_version,
            self.partition.value,
        )


@dataclass(frozen=True, slots=True)
class AblationContribution:
    component: AlphaComponent
    matched_cohort_count: int
    expectancy_with_component: Decimal | None
    expectancy_without_component: Decimal | None
    delta_expectancy: Decimal | None
    delta_win_rate: Decimal | None
    delta_average_winner_r: Decimal | None
    delta_average_loser_r: Decimal | None
    delta_profit_factor: Decimal | None
    delta_drawdown: Decimal | None
    delta_trade_count: int | None
    delta_holding_period: Decimal | None
    evidence_quality: EvidenceQuality
    matching_definition: str


@dataclass(frozen=True, slots=True)
class ContributionEstimate:
    component: AlphaComponent
    standalone_contribution: Decimal | None
    marginal_contribution: Decimal | None
    conditional_contribution: Decimal | None
    leave_one_out_contribution: Decimal | None
    permutation_importance: Decimal | None
    confidence_interval_low: Decimal | None
    confidence_interval_high: Decimal | None
    sample_size: int
    completed_partition_count: int
    partition_contributions: MappingProxyType[str, Decimal]
    method_label: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "partition_contributions",
            MappingProxyType(dict(sorted(self.partition_contributions.items()))),
        )


@dataclass(frozen=True, slots=True)
class OverlapFinding:
    component_a: AlphaComponent
    component_b: AlphaComponent
    sample_size: int
    score_correlation: Decimal | None
    candidate_overlap: Decimal | None
    approval_overlap: Decimal | None
    mutual_information: Decimal | None
    shared_source_lineage: bool
    setup_redundancy: Decimal | None
    regime_redundancy: Decimal | None
    redundancy_class: RedundancyClass
    recommended_action: str


@dataclass(frozen=True, slots=True)
class StabilityAssessment:
    component: AlphaComponent
    sample_size: int
    directional_stability: Decimal | None
    magnitude_stability: Decimal | None
    rank_stability: Decimal | None
    sector_stability: Decimal | None
    setup_stability: Decimal | None
    regime_stability: Decimal | None
    horizon_stability: Decimal | None
    era_stability: Decimal | None
    holdout_consistency: bool | None
    forward_consistency: bool | None
    classification: StabilityClass
    evidence_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    component: AlphaComponent
    confidence: ContributionConfidence
    sample_size: int
    holdout_sample_size: int
    forward_sample_size: int
    uncertainty_penalty: Decimal
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposalGuardrails:
    maximum_relative_change: Decimal = Decimal("0.20")
    maximum_absolute_weight: Decimal = Decimal("30")
    minimum_absolute_weight: Decimal = Decimal("0")
    weak_evidence_shrinkage: Decimal = Decimal("0.80")
    moderate_evidence_shrinkage: Decimal = Decimal("0.50")
    strong_evidence_shrinkage: Decimal = Decimal("0.20")
    minimum_holdout_samples: int = 10
    minimum_forward_samples: int = 10
    overlap_penalty: Decimal = Decimal("0.70")

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.maximum_relative_change <= Decimal("1"):
            raise ValueError("maximum relative change must be in [0, 1]")
        if self.maximum_absolute_weight > Decimal("100"):
            raise ValueError("maximum component weight cannot exceed 100")
        if self.minimum_absolute_weight < Decimal("0"):
            raise ValueError("minimum component weight cannot be negative")


@dataclass(frozen=True, slots=True)
class ComponentWeightDecision:
    component: AlphaComponent
    current_weight: Decimal
    proposed_raw_weight: Decimal
    proposed_weight: Decimal
    absolute_change: Decimal
    relative_change: Decimal
    payoff_multiplier: Decimal
    confidence_multiplier: Decimal
    stability_multiplier: Decimal
    uniqueness_multiplier: Decimal
    decision: ComponentDecisionState
    primary_reason: str
    supporting_metrics: tuple[str, ...]
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeightProposal:
    baseline: WeightSet
    proposed: WeightSet
    decisions: tuple[ComponentWeightDecision, ...]
    guardrails: ProposalGuardrails
    evidence_count: int
    validation_status: str
    holdout_status: str
    forward_status: str
    research_only: bool = True
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence or not self.research_only:
            raise ValueError("adaptive proposals must remain research-only")


@dataclass(frozen=True, slots=True)
class ConditionalWeightSet:
    setup: str | None
    regime: str | None
    horizon: str | None
    sample_size: int
    weights: WeightSet
    evidence_quality: EvidenceQuality

    @property
    def key(self) -> tuple[str | None, str | None, str | None]:
        return (self.setup, self.regime, self.horizon)


@dataclass(frozen=True, slots=True)
class ConditionalWeightPolicy:
    universal: WeightSet | None
    conditionals: tuple[ConditionalWeightSet, ...]
    minimum_sample_size: int
    research_only: bool = True


@dataclass(frozen=True, slots=True)
class ResolvedWeightSet:
    weights: WeightSet
    hierarchy_level: HierarchyLevel
    matched_condition: str


@dataclass(frozen=True, slots=True)
class CandidateWeightPolicy:
    policy_id: str
    parent_policy: str
    canonical_weights: WeightSet
    proposed_weights: WeightSet
    conditional_weights: tuple[ConditionalWeightSet, ...]
    evidence_window: str
    dataset_version: str
    outcome_count: int
    method_version: str
    guardrails: ProposalGuardrails
    quality_state: EvidenceQuality
    validation_status: str
    holdout_status: str
    forward_status: str
    state: CandidatePolicyState
    created_at: datetime
    manifest_hash: str
    component_decisions: tuple[ComponentWeightDecision, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("candidate policies cannot influence production")
        if not self.policy_id.startswith("ALPHA_WEIGHT_RESEARCH_"):
            raise ValueError("candidate policy ID has an invalid namespace")
        if self.proposed_weights.layer is not WeightLayer.RESEARCH_PROPOSED_WEIGHTS:
            raise ValueError("candidate policies require research-proposed weights")
        if self.outcome_count < 0 or not self.manifest_hash:
            raise ValueError(
                "candidate policy requires outcome count and manifest hash"
            )


@dataclass(frozen=True, slots=True)
class PolicyComparison:
    baseline_policy: str
    candidate_policy: str
    partition: EvidencePartition
    baseline: ResearchPerformance
    candidate: ResearchPerformance
    symbol_count: int
    sector_count: int
    setup_count: int


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    candidate_policy: str
    decision: PromotionDecision
    blockers: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    required_next_step: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class AdaptiveWeightResearchReport:
    evidence_count: int
    partition_counts: MappingProxyType[str, int]
    contributions: tuple[ContributionEstimate, ...]
    ablations: tuple[AblationContribution, ...]
    overlaps: tuple[OverlapFinding, ...]
    stabilities: tuple[StabilityAssessment, ...]
    proposal: WeightProposal
    candidate_policy: CandidateWeightPolicy | None
    promotion: PromotionAssessment | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "partition_counts",
            MappingProxyType(dict(sorted(self.partition_counts.items()))),
        )


def to_primitive(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, MappingProxyType):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in fields(value)
        }
    return value


__all__ = [
    "ADAPTIVE_WEIGHT_METHOD_VERSION",
    "ADAPTIVE_WEIGHT_SCHEMA_VERSION",
    "AUTOMATIC_DEPLOYMENT",
    "AUTOMATIC_WEIGHT_MUTATION",
    "CANONICAL_COMPONENT_WEIGHTS",
    "CANONICAL_WEIGHTS_IMMUTABLE",
    "FORWARD_VALIDATION_REQUIRED",
    "HOLDOUT_REQUIRED",
    "OVERLAP_PENALTY_REQUIRED",
    "POLICY_VERSIONING_REQUIRED",
    "PRODUCTION_INFLUENCE",
    "AblationContribution",
    "AblationObservation",
    "AblationRole",
    "AdaptiveWeightResearchReport",
    "AlphaComponent",
    "CandidatePolicyState",
    "CandidateWeightPolicy",
    "ComponentDecisionState",
    "ComponentScore",
    "ComponentWeight",
    "ComponentWeightDecision",
    "CompletedOutcomeEvidence",
    "ConditionalWeightPolicy",
    "ConditionalWeightSet",
    "ConfidenceAssessment",
    "ContributionConfidence",
    "ContributionEstimate",
    "EvidencePartition",
    "EvidenceQuality",
    "HierarchyLevel",
    "OverlapFinding",
    "PolicyComparison",
    "PromotionAssessment",
    "PromotionDecision",
    "ProposalGuardrails",
    "RedundancyClass",
    "ResearchPerformance",
    "ResolvedWeightSet",
    "StabilityAssessment",
    "StabilityClass",
    "WeightLayer",
    "WeightProposal",
    "WeightSet",
    "canonical_weight_set",
    "deployed_weight_set",
    "to_primitive",
]
