from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from alpha.continuous_learning.models import (
    CalibrationBucket,
    ConfidenceCalibrationReport,
    LearningConfidence,
    LearningThresholds,
    PredictionAssessment,
)


class ConfidenceCalibrationEngine:
    """Measure reliability of frozen confidence labels; never rewrite confidence."""

    def __init__(self, thresholds: LearningThresholds | None = None) -> None:
        self.thresholds = thresholds or LearningThresholds()

    def assess(
        self, predictions: tuple[PredictionAssessment, ...]
    ) -> ConfidenceCalibrationReport:
        resolved = tuple(
            item
            for item in predictions
            if item.predicted_probability is not None
            and item.observed_success is not None
        )
        grouped: dict[Decimal, list[PredictionAssessment]] = defaultdict(list)
        for item in resolved:
            assert item.predicted_probability is not None
            grouped[item.predicted_probability].append(item)
        buckets = tuple(
            _bucket(probability, tuple(rows))
            for probability, rows in sorted(grouped.items(), reverse=True)
        )
        brier = _brier(resolved)
        ece = _ece(buckets, len(resolved))
        confidence = _confidence(len(resolved))
        status = (
            "INSUFFICIENT_EVIDENCE"
            if ece is None or confidence is LearningConfidence.INSUFFICIENT
            else "SIGNIFICANT_MISCALIBRATION"
            if ece >= self.thresholds.calibration_significant
            else "CALIBRATION_WATCH"
            if ece >= self.thresholds.calibration_warning
            else "CALIBRATION_ACCEPTABLE"
        )
        return ConfidenceCalibrationReport(
            completed_predictions=len(resolved),
            brier_score=brier,
            expected_calibration_error=ece,
            buckets=buckets,
            confidence=confidence,
            status=status,
            assumptions=(
                "HIGH confidence maps to 0.80, MEDIUM to 0.60, and LOW to 0.40.",
                "Mappings are transparent diagnostic assumptions, not production "
                "probabilities.",
                "Unresolved outcomes are excluded rather than treated as failures.",
            ),
        )


def _bucket(
    probability: Decimal,
    rows: tuple[PredictionAssessment, ...],
) -> CalibrationBucket:
    successes = sum(1 for item in rows if item.observed_success is True)
    observed = _q(Decimal(successes) / Decimal(len(rows)))
    label = {
        Decimal("0.80"): "HIGH",
        Decimal("0.60"): "MEDIUM",
        Decimal("0.40"): "LOW",
    }.get(probability, str(probability))
    return CalibrationBucket(
        confidence_label=label,
        predicted_probability=probability,
        sample_count=len(rows),
        observed_success_rate=observed,
        calibration_error=_q(abs(probability - observed)),
    )


def _brier(rows: tuple[PredictionAssessment, ...]) -> Decimal | None:
    if not rows:
        return None
    total = Decimal("0")
    for item in rows:
        assert item.predicted_probability is not None
        observed = Decimal("1") if item.observed_success else Decimal("0")
        total += (item.predicted_probability - observed) ** 2
    return _q(total / Decimal(len(rows)))


def _ece(buckets: tuple[CalibrationBucket, ...], total: int) -> Decimal | None:
    if not buckets or total <= 0:
        return None
    value = sum(
        (
            (item.calibration_error or Decimal("0"))
            * Decimal(item.sample_count)
            / Decimal(total)
            for item in buckets
        ),
        start=Decimal("0"),
    )
    return _q(value)


def _confidence(count: int) -> LearningConfidence:
    if count < 20:
        return LearningConfidence.INSUFFICIENT
    if count < 30:
        return LearningConfidence.LOW
    if count < 50:
        return LearningConfidence.MEDIUM
    return LearningConfidence.HIGH


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


__all__ = ["ConfidenceCalibrationEngine"]
