from __future__ import annotations

from decimal import Decimal

from alpha.continuous_learning.models import (
    LearningOutcomeStatus,
    OutcomeObservation,
    PredictionAssessment,
)

_CONFIDENCE_PROBABILITY = {
    "HIGH": Decimal("0.80"),
    "VERY_HIGH": Decimal("0.80"),
    "STRONG": Decimal("0.80"),
    "MEDIUM": Decimal("0.60"),
    "MODERATE": Decimal("0.60"),
    "LOW": Decimal("0.40"),
}


class PredictionTracker:
    """Compare frozen predictions with observed outcomes without recalculation."""

    def assess(
        self, observations: tuple[OutcomeObservation, ...]
    ) -> tuple[PredictionAssessment, ...]:
        return tuple(self._assess(item) for item in observations)

    def _assess(self, item: OutcomeObservation) -> PredictionAssessment:
        expected = _expected_direction(item.final_verdict)
        actual = _actual_direction(item.realised_return_pct)
        completed = item.status is LearningOutcomeStatus.EXITED
        direction_correct = (
            None
            if not completed or actual is None or expected == "NEUTRAL"
            else expected == actual
        )
        correct = _recommendation_correct(item, actual) if completed else None
        timing = (
            "ENTRY_ACHIEVED"
            if item.entry_achieved
            else "ENTRY_MISSED"
            if item.entry_missed
            else "PENDING"
        )
        exit_quality = (
            "TARGET_EXIT"
            if item.target_1_hit or item.target_2_hit or item.target_3_hit
            else "STOP_EXIT"
            if item.stop_hit
            else "TIME_EXIT"
            if item.time_exit
            else "UNRESOLVED"
        )
        explanation = (
            f"Frozen verdict expected {expected.lower()} direction.",
            (
                "Outcome is unresolved; correctness is not estimated."
                if correct is None
                else f"Observed outcome was {actual.lower() if actual else 'flat'}."
            ),
            f"Timing status: {timing}.",
            f"Exit status: {exit_quality}.",
        )
        return PredictionAssessment(
            recommendation_id=item.recommendation_id,
            symbol=item.symbol,
            assessed_at=item.observed_at,
            expected_direction=expected,
            actual_direction=actual,
            recommendation_correct=correct,
            direction_correct=direction_correct,
            timing_quality=timing,
            exit_quality=exit_quality,
            predicted_probability=_CONFIDENCE_PROBABILITY.get(
                item.predicted_confidence.strip().upper()
            ),
            observed_success=correct,
            explanation=explanation,
        )


def _expected_direction(verdict: str) -> str:
    normalized = verdict.strip().upper().replace(" ", "_")
    if normalized in {"BUY", "STRONG_BUY", "ACCUMULATE"}:
        return "UP"
    if normalized in {"SELL", "STRONG_SELL", "REDUCE", "REJECT"}:
        return "DOWN"
    return "NEUTRAL"


def _actual_direction(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value > Decimal("0"):
        return "UP"
    if value < Decimal("0"):
        return "DOWN"
    return "FLAT"


def _recommendation_correct(
    observation: OutcomeObservation, actual: str | None
) -> bool | None:
    if actual is None:
        return None
    expected = _expected_direction(observation.final_verdict)
    if expected == "NEUTRAL":
        return actual != "UP"
    return actual == expected


__all__ = ["PredictionTracker"]
