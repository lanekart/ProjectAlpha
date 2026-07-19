from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
CLL_SCHEMA_VERSION = "continuous-learning-v1"


class LearningOutcomeStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"
    EXPIRED = "EXPIRED"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    DATA_MISSING = "DATA_MISSING"


class DriftStatus(StrEnum):
    NO_DRIFT = "NO_DRIFT"
    EARLY_DRIFT = "EARLY_DRIFT"
    SIGNIFICANT_DRIFT = "SIGNIFICANT_DRIFT"
    UNKNOWN = "UNKNOWN"


class StrategyHealthClassification(StrEnum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADING = "DEGRADING"
    RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
    RETIRE = "RETIRE"


class LearningConfidence(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    observation_id: str
    recommendation_id: str
    observed_at: datetime
    generated_at: datetime
    symbol: str
    final_verdict: str
    predicted_confidence: str
    predicted_score: Decimal
    setup_type: str
    status: LearningOutcomeStatus
    entry_achieved: bool
    entry_missed: bool
    stop_hit: bool
    target_1_hit: bool
    target_2_hit: bool
    target_3_hit: bool
    time_exit: bool
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    realised_return_pct: Decimal | None
    holding_period_days: int | None
    market_regime: str | None
    sector: str | None
    volatility: Decimal | None
    liquidity: Decimal | None
    source: str
    evidence_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if self.production_influence:
            raise ValueError("learning observations cannot influence production")
        if not self.observation_id or not self.recommendation_id or not self.symbol:
            raise ValueError("learning observation identity is required")
        if self.holding_period_days is not None and self.holding_period_days < 0:
            raise ValueError("holding period cannot be negative")


@dataclass(frozen=True, slots=True)
class PredictionAssessment:
    recommendation_id: str
    symbol: str
    assessed_at: datetime
    expected_direction: str
    actual_direction: str | None
    recommendation_correct: bool | None
    direction_correct: bool | None
    timing_quality: str
    exit_quality: str
    predicted_probability: Decimal | None
    observed_success: bool | None
    explanation: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyHealth:
    strategy_key: str
    sample_count: int
    completed_count: int
    win_rate_pct: Decimal | None
    expectancy_pct: Decimal | None
    maximum_drawdown_pct: Decimal | None
    trade_frequency_per_month: Decimal | None
    precision_pct: Decimal | None
    recall_pct: Decimal | None
    stability_score: Decimal | None
    confidence: LearningConfidence
    health_score: Decimal | None
    classification: StrategyHealthClassification
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriftAssessment:
    drift_id: str
    dimension: str
    baseline_count: int
    recent_count: int
    baseline_value: Decimal | None
    recent_value: Decimal | None
    absolute_change: Decimal | None
    status: DriftStatus
    confidence: LearningConfidence
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    confidence_label: str
    predicted_probability: Decimal
    sample_count: int
    observed_success_rate: Decimal | None
    calibration_error: Decimal | None


@dataclass(frozen=True, slots=True)
class ConfidenceCalibrationReport:
    completed_predictions: int
    brier_score: Decimal | None
    expected_calibration_error: Decimal | None
    buckets: tuple[CalibrationBucket, ...]
    confidence: LearningConfidence
    status: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchRecommendation:
    recommendation_id: str
    priority: str
    subsystem: str
    title: str
    evidence_ids: tuple[str, ...]
    evidence_summary: str
    recommended_research: str
    confidence: LearningConfidence
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("learning research cannot influence production")
        if not self.evidence_ids:
            raise ValueError("learning research requires evidence")


@dataclass(frozen=True, slots=True)
class LearningEvent:
    event_id: str
    occurred_at: datetime
    recommendation_id: str | None
    event_type: str
    learning: str
    evidence: tuple[str, ...]
    confidence: LearningConfidence
    suggested_research: str | None
    source_observation_id: str | None
    outcome: str | None = None
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        if self.production_influence:
            raise ValueError("learning events cannot influence production")
        if not self.event_id or not self.event_type or not self.learning:
            raise ValueError("learning event identity and learning are required")


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    recommendations_seen: int
    registry_recommendations: int
    retained_historical_recommendations: int
    observations_generated: int
    observations_inserted: int
    learning_events_inserted: int
    pending_count: int
    completed_count: int
    missing_data_count: int


@dataclass(frozen=True, slots=True)
class ContinuousLearningReport:
    generated_at: datetime
    todays_recommendations: int
    outcomes: tuple[OutcomeObservation, ...]
    analytically_eligible_recommendations: int
    quarantined_recommendations: int
    predictions: tuple[PredictionAssessment, ...]
    strategy_health: tuple[StrategyHealth, ...]
    drifts: tuple[DriftAssessment, ...]
    calibration: ConfidenceCalibrationReport
    research_recommendations: tuple[ResearchRecommendation, ...]
    confidence_trend: str
    deployment_status: str
    overall_learning_confidence: LearningConfidence
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        if self.production_influence:
            raise ValueError("continuous learning reports cannot influence production")


@dataclass(frozen=True, slots=True)
class LearningThresholds:
    minimum_drift_segment: int = 10
    minimum_health_sample: int = 20
    strong_health_sample: int = 30
    retirement_evidence_sample: int = 50
    early_precision_drop_pp: Decimal = Decimal("7.5")
    significant_precision_drop_pp: Decimal = Decimal("15")
    early_expectancy_drop_pct: Decimal = Decimal("1")
    significant_expectancy_drop_pct: Decimal = Decimal("2")
    calibration_warning: Decimal = Decimal("0.15")
    calibration_significant: Decimal = Decimal("0.25")
    version: str = "cll-research-assumptions-v1"
    rationale: str = (
        "Explicit diagnostic assumptions; they do not alter production confidence, "
        "approval, allocation, or trading thresholds."
    )


def immutable_mapping(value: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(dict(sorted(value.items())))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CLL_SCHEMA_VERSION",
    "PRODUCTION_INFLUENCE",
    "CalibrationBucket",
    "CollectionSummary",
    "ConfidenceCalibrationReport",
    "ContinuousLearningReport",
    "DriftAssessment",
    "DriftStatus",
    "LearningConfidence",
    "LearningEvent",
    "LearningOutcomeStatus",
    "LearningThresholds",
    "OutcomeObservation",
    "PredictionAssessment",
    "ResearchRecommendation",
    "StrategyHealth",
    "StrategyHealthClassification",
]
