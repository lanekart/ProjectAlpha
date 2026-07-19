from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from alpha.continuous_learning.models import (
    DriftAssessment,
    DriftStatus,
    LearningConfidence,
    LearningThresholds,
    OutcomeObservation,
)


class FeatureDriftEngine:
    """Measure input-population shifts separately from outcome concept drift."""

    def __init__(self, thresholds: LearningThresholds | None = None) -> None:
        self.thresholds = thresholds or LearningThresholds()

    def assess(
        self, observations: tuple[OutcomeObservation, ...]
    ) -> tuple[DriftAssessment, ...]:
        ordered = tuple(sorted(observations, key=lambda item: item.generated_at))
        if len(ordered) < self.thresholds.minimum_drift_segment * 2:
            return (
                _unknown("feature-score", "RECOMMENDATION_SCORE", len(ordered)),
                _unknown("feature-volatility", "VOLATILITY", len(ordered)),
                _unknown("feature-sector", "SECTOR_MIX", len(ordered)),
            )
        midpoint = len(ordered) // 2
        baseline, recent = ordered[:midpoint], ordered[midpoint:]
        return (
            _numeric(
                "feature-score",
                "RECOMMENDATION_SCORE",
                baseline,
                recent,
                lambda row: row.predicted_score,
            ),
            _numeric(
                "feature-volatility",
                "VOLATILITY",
                baseline,
                recent,
                lambda row: row.volatility,
            ),
            _categorical("feature-sector", "SECTOR_MIX", baseline, recent),
        )


def _numeric(
    drift_id: str,
    dimension: str,
    baseline_rows: tuple[OutcomeObservation, ...],
    recent_rows: tuple[OutcomeObservation, ...],
    getter: object,
) -> DriftAssessment:
    assert callable(getter)
    baseline_values = tuple(
        value for row in baseline_rows if (value := getter(row)) is not None
    )
    recent_values = tuple(
        value for row in recent_rows if (value := getter(row)) is not None
    )
    if not baseline_values or not recent_values:
        return _unknown(drift_id, dimension, len(baseline_values) + len(recent_values))
    baseline = _average(baseline_values)
    recent = _average(recent_values)
    scale = max(abs(baseline), Decimal("1"))
    relative_change = abs(recent - baseline) / scale * Decimal("100")
    status = (
        DriftStatus.SIGNIFICANT_DRIFT
        if relative_change >= Decimal("30")
        else DriftStatus.EARLY_DRIFT
        if relative_change >= Decimal("15")
        else DriftStatus.NO_DRIFT
    )
    return DriftAssessment(
        drift_id=drift_id,
        dimension=dimension,
        baseline_count=len(baseline_values),
        recent_count=len(recent_values),
        baseline_value=_q(baseline),
        recent_value=_q(recent),
        absolute_change=_q(recent - baseline),
        status=status,
        confidence=_confidence(min(len(baseline_values), len(recent_values))),
        evidence=(
            "Feature drift compares chronological earlier and recent "
            "recommendation populations.",
            f"Absolute relative mean shift={_q(relative_change)} percent.",
        ),
    )


def _categorical(
    drift_id: str,
    dimension: str,
    baseline_rows: tuple[OutcomeObservation, ...],
    recent_rows: tuple[OutcomeObservation, ...],
) -> DriftAssessment:
    baseline_valid = tuple(row for row in baseline_rows if row.sector)
    recent_valid = tuple(row for row in recent_rows if row.sector)
    if len(baseline_valid) < 10 or len(recent_valid) < 10:
        return _unknown(
            drift_id,
            dimension,
            len(baseline_valid) + len(recent_valid),
        )
    baseline = Counter(row.sector for row in baseline_valid)
    recent = Counter(row.sector for row in recent_valid)
    categories = set(baseline) | set(recent)
    distance = sum(
        abs(
            Decimal(baseline.get(key, 0)) / Decimal(len(baseline_valid))
            - Decimal(recent.get(key, 0)) / Decimal(len(recent_valid))
        )
        for key in categories
    ) / Decimal("2")
    status = (
        DriftStatus.SIGNIFICANT_DRIFT
        if distance >= Decimal("0.30")
        else DriftStatus.EARLY_DRIFT
        if distance >= Decimal("0.15")
        else DriftStatus.NO_DRIFT
    )
    return DriftAssessment(
        drift_id=drift_id,
        dimension=dimension,
        baseline_count=len(baseline_valid),
        recent_count=len(recent_valid),
        baseline_value=None,
        recent_value=None,
        absolute_change=_q(distance * Decimal("100")),
        status=status,
        confidence=_confidence(min(len(baseline_valid), len(recent_valid))),
        evidence=(
            "Sector mix shift uses total variation distance.",
            f"Distribution distance={_q(distance * Decimal('100'))} percent.",
        ),
    )


def _unknown(drift_id: str, dimension: str, count: int) -> DriftAssessment:
    return DriftAssessment(
        drift_id=drift_id,
        dimension=dimension,
        baseline_count=count // 2,
        recent_count=count - count // 2,
        baseline_value=None,
        recent_value=None,
        absolute_change=None,
        status=DriftStatus.UNKNOWN,
        confidence=LearningConfidence.INSUFFICIENT,
        evidence=(
            "Insufficient or unavailable feature evidence for drift estimation.",
        ),
    )


def _average(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _confidence(count: int) -> LearningConfidence:
    if count < 10:
        return LearningConfidence.INSUFFICIENT
    if count < 20:
        return LearningConfidence.LOW
    if count < 50:
        return LearningConfidence.MEDIUM
    return LearningConfidence.HIGH


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = ["FeatureDriftEngine"]
