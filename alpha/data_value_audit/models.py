"""Immutable domain models for the Data Value and ROI Audit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DVRA_VERSION = "DVRA_v1.0"
PRODUCTION_INFLUENCE = False


class DatasetDomain(StrEnum):
    MARKET_DATA = "MARKET_DATA"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    IDENTITY = "IDENTITY"
    INDEX = "INDEX"
    DELIVERY = "DELIVERY"
    OWNERSHIP = "OWNERSHIP"
    EARNINGS = "EARNINGS"
    MARKET_CONTEXT = "MARKET_CONTEXT"


class NoveltyClass(StrEnum):
    RECONCILES_CORE_TRUTH = "RECONCILES_CORE_TRUTH"
    ADDS_POINT_IN_TIME_CONTEXT = "ADDS_POINT_IN_TIME_CONTEXT"
    ADDS_NEW_FEATURE = "ADDS_NEW_FEATURE"
    REFINES_EXISTING_FEATURE = "REFINES_EXISTING_FEATURE"
    MOSTLY_DUPLICATIVE = "MOSTLY_DUPLICATIVE"


class ImpactLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class ComplexityLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class CostStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    NO_LICENSE_FEE_IDENTIFIED = "NO_LICENSE_FEE_IDENTIFIED"
    BUNDLED = "BUNDLED"
    QUOTE_REQUIRED = "QUOTE_REQUIRED"
    UNKNOWN = "UNKNOWN"


class ROIClass(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Subsystem(StrEnum):
    REPLAY = "REPLAY"
    FEATURE_ATTRIBUTION = "FEATURE_ATTRIBUTION"
    CANDIDATE_GENERATION = "CANDIDATE_GENERATION"
    GATE_TRUTH = "GATE_TRUTH"
    MARKET_OPPORTUNITY = "MARKET_OPPORTUNITY"
    MARKET_DNA = "MARKET_DNA"
    STRATEGY_LAB = "STRATEGY_LAB"
    LEARNING = "LEARNING"
    PERFORMANCE = "PERFORMANCE"
    PORTFOLIO = "PORTFOLIO"
    MARKET_REGIME = "MARKET_REGIME"
    POINT_IN_TIME_UNIVERSE = "POINT_IN_TIME_UNIVERSE"
    TRADE_PLAN = "TRADE_PLAN"
    DATA_PLATFORM = "DATA_PLATFORM"


class DecisionDimension(StrEnum):
    CANDIDATE_QUALITY = "CANDIDATE_QUALITY"
    APPROVAL_QUALITY = "APPROVAL_QUALITY"
    OPPORTUNITY_RECALL = "OPPORTUNITY_RECALL"
    TRADE_QUALITY = "TRADE_QUALITY"
    CAPITAL_ALLOCATION = "CAPITAL_ALLOCATION"
    PORTFOLIO_CONSTRUCTION = "PORTFOLIO_CONSTRUCTION"


class ReplayMetric(StrEnum):
    CAGR = "CAGR"
    DRAWDOWN = "DRAWDOWN"
    SHARPE = "SHARPE"
    OPPORTUNITY_CAPTURE = "OPPORTUNITY_CAPTURE"
    CANDIDATE_RECALL = "CANDIDATE_RECALL"
    APPROVAL_RECALL = "APPROVAL_RECALL"


@dataclass(frozen=True, slots=True)
class DimensionImpact:
    dimension: DecisionDimension
    impact: ImpactLevel
    reason: str


@dataclass(frozen=True, slots=True)
class ReplayImpact:
    metric: ReplayMetric
    impact: ImpactLevel
    reason: str


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    dataset_id: str
    name: str
    domain: DatasetDomain
    novelty: NoveltyClass
    bias_control: ImpactLevel
    authority: ImpactLevel
    point_in_time_value: ImpactLevel
    direct_feature_value: ImpactLevel
    evidence_sources: tuple[str, ...]
    feature_gap: str
    decision_impacts: tuple[DimensionImpact, ...]
    subsystems: tuple[Subsystem, ...]
    replay_impacts: tuple[ReplayImpact, ...]
    dependencies: tuple[str, ...] = ()
    unlocks: tuple[str, ...] = ()
    package_parent: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.name.strip():
            raise ValueError("dataset identity cannot be empty")
        dimensions = tuple(item.dimension for item in self.decision_impacts)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError(f"duplicate decision dimension for {self.dataset_id}")
        replay_metrics = tuple(item.metric for item in self.replay_impacts)
        if len(replay_metrics) != len(set(replay_metrics)):
            raise ValueError(f"duplicate replay metric for {self.dataset_id}")


@dataclass(frozen=True, slots=True)
class InformationGainAssessment:
    dataset_id: str
    score: int
    novelty_points: int
    bias_control_points: int
    authority_points: int
    point_in_time_points: int
    evidence_points: int
    confidence: ConfidenceLevel
    rationale: str


@dataclass(frozen=True, slots=True)
class DecisionGainAssessment:
    dataset_id: str
    score: int
    impacts: tuple[DimensionImpact, ...]
    confidence: ConfidenceLevel
    primary_gain: str


@dataclass(frozen=True, slots=True)
class InfrastructureGainAssessment:
    dataset_id: str
    score: int
    subsystem_count: int
    subsystems: tuple[Subsystem, ...]
    primary_unlock: str


@dataclass(frozen=True, slots=True)
class ReplayGainAssessment:
    dataset_id: str
    overall: ImpactLevel
    impacts: tuple[ReplayImpact, ...]
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class FeatureGapAssessment:
    dataset_id: str
    gap: str
    current_state: str
    expected_resolution: str
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class CostAssessment:
    dataset_id: str
    status: CostStatus
    initial_cost_inr: int | None
    annual_cost_inr: int | None
    engineering_cost: ComplexityLevel
    maintenance_cost: ComplexityLevel
    licensing_risk: RiskLevel
    legal_risk: RiskLevel
    source: str
    notes: str


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source_dataset_id: str
    target: str
    relationship: str


@dataclass(frozen=True, slots=True)
class SensitivityAssessment:
    dataset_id: str
    unavailable_effect: str
    dependent_unlocks_lost: int
    value_score_lost: int
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class DatasetReportCard:
    candidate: DatasetCandidate
    information: InformationGainAssessment
    decision: DecisionGainAssessment
    infrastructure: InfrastructureGainAssessment
    replay: ReplayGainAssessment
    feature_gap: FeatureGapAssessment
    cost: CostAssessment
    gross_value_score: int
    priority_index: int | None
    roi_class: ROIClass
    roi_confidence: ConfidenceLevel
    overall_rationale: str


@dataclass(frozen=True, slots=True)
class BudgetPlan:
    budget_id: str
    title: str
    annual_budget_inr: int | None
    selected_dataset_ids: tuple[str, ...]
    known_annual_spend_inr: int
    unallocated_inr: int | None
    procurement_instruction: str
    rationale: str
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataValueAuditReport:
    version: str
    cards: tuple[DatasetReportCard, ...]
    dependencies: tuple[DependencyEdge, ...]
    sensitivity: tuple[SensitivityAssessment, ...]
    budgets: tuple[BudgetPlan, ...]
    methodology: str
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DVRA cannot influence production")
        ids = tuple(card.candidate.dataset_id for card in self.cards)
        if len(ids) != len(set(ids)):
            raise ValueError("DVRA report contains duplicate datasets")

    @property
    def ranked_estimable(self) -> tuple[DatasetReportCard, ...]:
        return tuple(
            sorted(
                (card for card in self.cards if card.priority_index is not None),
                key=lambda card: (-int(card.priority_index or 0), card.candidate.name),
            )
        )
