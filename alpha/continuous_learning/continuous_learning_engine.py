from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from alpha.continuous_learning.concept_drift_engine import ConceptDriftEngine
from alpha.continuous_learning.confidence_calibration import (
    ConfidenceCalibrationEngine,
)
from alpha.continuous_learning.feature_drift_engine import FeatureDriftEngine
from alpha.continuous_learning.learning_registry import ContinuousLearningRegistry
from alpha.continuous_learning.models import (
    CollectionSummary,
    ContinuousLearningReport,
    LearningConfidence,
    LearningEvent,
    LearningOutcomeStatus,
    OutcomeObservation,
    ResearchRecommendation,
)
from alpha.continuous_learning.outcome_collector import OutcomeCollector
from alpha.continuous_learning.prediction_tracker import PredictionTracker
from alpha.continuous_learning.research_trigger_engine import ResearchTriggerEngine
from alpha.continuous_learning.strategy_health_monitor import StrategyHealthMonitor
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.service import resolve_ledger_path


class ContinuousLearningEngine:
    """Coordinate immutable evidence collection and advisory learning analysis."""

    def __init__(
        self,
        *,
        performance_repository: RecommendationLedgerRepository,
        forward_registry: ForwardValidationRegistry,
        learning_registry: ContinuousLearningRegistry,
        collector: OutcomeCollector | None = None,
        prediction_tracker: PredictionTracker | None = None,
        concept_drift: ConceptDriftEngine | None = None,
        feature_drift: FeatureDriftEngine | None = None,
        health_monitor: StrategyHealthMonitor | None = None,
        calibration: ConfidenceCalibrationEngine | None = None,
        research_trigger: ResearchTriggerEngine | None = None,
    ) -> None:
        self.performance_repository = performance_repository
        self.forward_registry = forward_registry
        self.learning_registry = learning_registry
        self.collector = collector or OutcomeCollector()
        self.prediction_tracker = prediction_tracker or PredictionTracker()
        self.concept_drift = concept_drift or ConceptDriftEngine()
        self.feature_drift = feature_drift or FeatureDriftEngine()
        self.health_monitor = health_monitor or StrategyHealthMonitor()
        self.calibration_engine = calibration or ConfidenceCalibrationEngine()
        self.research_trigger = research_trigger or ResearchTriggerEngine()

    @classmethod
    def from_paths(
        cls,
        *,
        performance_ledger: Path | str | None = None,
        forward_registry: Path | str | None = None,
        learning_registry: Path | str | None = None,
    ) -> ContinuousLearningEngine:
        return cls(
            performance_repository=RecommendationLedgerRepository(
                resolve_ledger_path(performance_ledger)
            ),
            forward_registry=ForwardValidationRegistry(forward_registry),
            learning_registry=ContinuousLearningRegistry(learning_registry),
        )

    def collect(self) -> CollectionSummary:
        observations = self.collector.collect(
            entries=self.performance_repository.load_entries(),
            outcomes=self.performance_repository.load_outcomes(),
            snapshots=self.forward_registry.load_snapshots(),
            events=self.forward_registry.load_events(),
        )
        inserted = self.learning_registry.append_observations(observations)
        predictions = self.prediction_tracker.assess(observations)
        prediction_events = tuple(
            _learning_event(item, prediction)
            for item, prediction in zip(observations, predictions, strict=True)
        )
        health = self.health_monitor.assess(observations)
        drifts = self.concept_drift.assess(observations) + self.feature_drift.assess(
            observations
        )
        calibration = self.calibration_engine.assess(predictions)
        recommendations = self.research_trigger.recommend(
            drifts=drifts,
            health=health,
            calibration=calibration,
        )
        occurred_at = max(
            (item.observed_at for item in observations),
            default=datetime(1970, 1, 1, tzinfo=UTC),
        )
        events = prediction_events + tuple(
            _research_event(item, occurred_at) for item in recommendations
        )
        event_inserted = self.learning_registry.append_learning_events(events)
        latest = self.learning_registry.latest_observations()
        current_ids = {item.recommendation_id for item in observations}
        return CollectionSummary(
            recommendations_seen=len(observations),
            registry_recommendations=len(latest),
            retained_historical_recommendations=sum(
                1 for item in latest if item.recommendation_id not in current_ids
            ),
            observations_generated=len(observations),
            observations_inserted=inserted,
            learning_events_inserted=event_inserted,
            pending_count=sum(
                1
                for item in observations
                if item.status
                in {LearningOutcomeStatus.PENDING, LearningOutcomeStatus.ACTIVE}
            ),
            completed_count=sum(
                1
                for item in observations
                if item.status is LearningOutcomeStatus.EXITED
            ),
            missing_data_count=sum(
                1
                for item in observations
                if item.status is LearningOutcomeStatus.DATA_MISSING
            ),
        )

    def report(self, *, collect_first: bool = True) -> ContinuousLearningReport:
        if collect_first:
            self.collect()
        observations = self.learning_registry.latest_observations()
        current_ids = self._current_source_recommendation_ids()
        eligible = tuple(
            item for item in observations if item.recommendation_id in current_ids
        )
        predictions = self.prediction_tracker.assess(eligible)
        health = self.health_monitor.assess(eligible)
        drifts = self.concept_drift.assess(eligible) + self.feature_drift.assess(
            eligible
        )
        calibration = self.calibration_engine.assess(predictions)
        research = self.research_trigger.recommend(
            drifts=drifts,
            health=health,
            calibration=calibration,
        )
        generated_at = max(
            (item.observed_at for item in observations),
            default=datetime(1970, 1, 1, tzinfo=UTC),
        )
        latest_date = max(
            (item.generated_at.date() for item in eligible),
            default=None,
        )
        latest_count = sum(
            1
            for item in eligible
            if latest_date is not None and item.generated_at.date() == latest_date
        )
        return ContinuousLearningReport(
            generated_at=generated_at,
            todays_recommendations=latest_count,
            outcomes=observations,
            analytically_eligible_recommendations=len(eligible),
            quarantined_recommendations=len(observations) - len(eligible),
            predictions=predictions,
            strategy_health=health,
            drifts=drifts,
            calibration=calibration,
            research_recommendations=research,
            confidence_trend=_confidence_trend(predictions),
            deployment_status="LEARNING_ONLY_NOT_A_DEPLOYMENT_DECISION",
            overall_learning_confidence=_overall_confidence(
                calibration.completed_predictions
            ),
        )

    def _current_source_recommendation_ids(self) -> frozenset[str]:
        performance_ids = {
            item.recommendation_id
            for item in self.performance_repository.load_entries()
        }
        forward_ids = {
            item.recommendation_id for item in self.forward_registry.load_snapshots()
        }
        return frozenset(performance_ids | forward_ids)


def _learning_event(
    observation: OutcomeObservation,
    prediction: object,
) -> LearningEvent:
    from alpha.continuous_learning.models import PredictionAssessment

    if not isinstance(prediction, PredictionAssessment):
        raise TypeError("prediction assessment required")
    correctness = prediction.recommendation_correct
    state = (
        "UNRESOLVED"
        if correctness is None
        else "CORRECT"
        if correctness
        else "INCORRECT"
    )
    learning = (
        f"{observation.symbol} prediction is {state}; "
        f"timing={prediction.timing_quality}; exit={prediction.exit_quality}."
    )
    evidence = (
        observation.evidence_hash,
        *prediction.explanation,
    )
    event_id = sha256(
        json.dumps(
            {
                "observation": observation.observation_id,
                "learning": learning,
                "evidence": evidence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return LearningEvent(
        event_id=event_id,
        occurred_at=observation.observed_at,
        recommendation_id=observation.recommendation_id,
        event_type="PREDICTION_OUTCOME_ASSESSMENT",
        learning=learning,
        evidence=evidence,
        confidence=(
            LearningConfidence.LOW
            if correctness is not None
            else LearningConfidence.INSUFFICIENT
        ),
        suggested_research=(
            "Include this observation in aggregated failure attribution."
            if correctness is False
            else None
        ),
        source_observation_id=observation.observation_id,
        outcome=observation.status.value,
    )


def _research_event(
    recommendation: ResearchRecommendation,
    occurred_at: datetime,
) -> LearningEvent:
    payload = {
        "recommendation": recommendation.recommendation_id,
        "occurred_at": occurred_at.isoformat(),
        "evidence": recommendation.evidence_summary,
        "research": recommendation.recommended_research,
    }
    return LearningEvent(
        event_id=sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        occurred_at=occurred_at,
        recommendation_id=None,
        event_type="RESEARCH_TRIGGER",
        learning=recommendation.title,
        evidence=(
            *recommendation.evidence_ids,
            recommendation.evidence_summary,
        ),
        confidence=recommendation.confidence,
        suggested_research=recommendation.recommended_research,
        source_observation_id=None,
        outcome=None,
    )


def _confidence_trend(predictions: tuple[object, ...]) -> str:
    from alpha.continuous_learning.models import PredictionAssessment

    resolved = tuple(
        item
        for item in predictions
        if isinstance(item, PredictionAssessment)
        and item.predicted_probability is not None
        and item.observed_success is not None
    )
    if len(resolved) < 20:
        return "UNKNOWN_INSUFFICIENT_COMPLETED_PREDICTIONS"
    midpoint = len(resolved) // 2
    earlier = _success_rate(resolved[:midpoint])
    recent = _success_rate(resolved[midpoint:])
    change = recent - earlier
    if change > Decimal("0.05"):
        return "IMPROVING"
    if change < Decimal("-0.05"):
        return "DETERIORATING"
    return "STABLE"


def _success_rate(values: tuple[object, ...]) -> Decimal:
    from alpha.continuous_learning.models import PredictionAssessment

    typed = tuple(item for item in values if isinstance(item, PredictionAssessment))
    return Decimal(sum(1 for item in typed if item.observed_success)) / Decimal(
        len(typed)
    )


def _overall_confidence(completed: int) -> LearningConfidence:
    if completed < 20:
        return LearningConfidence.INSUFFICIENT
    if completed < 30:
        return LearningConfidence.LOW
    if completed < 50:
        return LearningConfidence.MEDIUM
    return LearningConfidence.HIGH


__all__ = ["ContinuousLearningEngine"]
