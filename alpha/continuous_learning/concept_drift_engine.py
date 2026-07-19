from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.continuous_learning.models import (
    DriftAssessment,
    DriftStatus,
    LearningConfidence,
    LearningOutcomeStatus,
    LearningThresholds,
    OutcomeObservation,
)


class ConceptDriftEngine:
    """Detect chronological outcome deterioration with explicit sample guards."""

    def __init__(self, thresholds: LearningThresholds | None = None) -> None:
        self.thresholds = thresholds or LearningThresholds()

    def assess(
        self, observations: tuple[OutcomeObservation, ...]
    ) -> tuple[DriftAssessment, ...]:
        completed = tuple(
            sorted(
                (
                    item
                    for item in observations
                    if item.status is LearningOutcomeStatus.EXITED
                    and item.realised_return_pct is not None
                ),
                key=lambda item: (item.observed_at, item.recommendation_id),
            )
        )
        return (
            self._metric("concept-precision", "PRECISION", completed, _precision),
            self._metric("concept-expectancy", "EXPECTANCY", completed, _expectancy),
            self._timing(completed),
        )

    def _metric(
        self,
        drift_id: str,
        dimension: str,
        rows: tuple[OutcomeObservation, ...],
        metric: object,
    ) -> DriftAssessment:
        minimum = self.thresholds.minimum_drift_segment
        if len(rows) < minimum * 2:
            return _unknown(
                drift_id, dimension, len(rows) // 2, len(rows) - len(rows) // 2
            )
        midpoint = len(rows) // 2
        baseline_rows = rows[:midpoint]
        recent_rows = rows[midpoint:]
        calculator = metric
        assert callable(calculator)
        baseline = calculator(baseline_rows)
        recent = calculator(recent_rows)
        change = None if baseline is None or recent is None else _q(recent - baseline)
        status = self._status(dimension, change)
        return DriftAssessment(
            drift_id=drift_id,
            dimension=dimension,
            baseline_count=len(baseline_rows),
            recent_count=len(recent_rows),
            baseline_value=baseline,
            recent_value=recent,
            absolute_change=change,
            status=status,
            confidence=_confidence(min(len(baseline_rows), len(recent_rows))),
            evidence=(
                "Chronological completed outcomes were split into earlier and "
                "recent halves.",
                f"Earlier {dimension.lower()}={_text(baseline)}; "
                f"recent={_text(recent)}.",
                f"Research threshold version={self.thresholds.version}.",
            ),
        )

    def _timing(self, rows: tuple[OutcomeObservation, ...]) -> DriftAssessment:
        return self._metric(
            "concept-entry-timing",
            "ENTRY_TIMING_SUCCESS",
            rows,
            _entry_rate,
        )

    def _status(self, dimension: str, change: Decimal | None) -> DriftStatus:
        if change is None:
            return DriftStatus.UNKNOWN
        if dimension in {"PRECISION", "ENTRY_TIMING_SUCCESS"}:
            if change <= -self.thresholds.significant_precision_drop_pp:
                return DriftStatus.SIGNIFICANT_DRIFT
            if change <= -self.thresholds.early_precision_drop_pp:
                return DriftStatus.EARLY_DRIFT
        else:
            if change <= -self.thresholds.significant_expectancy_drop_pct:
                return DriftStatus.SIGNIFICANT_DRIFT
            if change <= -self.thresholds.early_expectancy_drop_pct:
                return DriftStatus.EARLY_DRIFT
        return DriftStatus.NO_DRIFT


def _precision(rows: tuple[OutcomeObservation, ...]) -> Decimal | None:
    if not rows:
        return None
    winners = sum(
        1
        for item in rows
        if item.realised_return_pct is not None and item.realised_return_pct > 0
    )
    return _q(Decimal(winners) / Decimal(len(rows)) * Decimal("100"))


def _expectancy(rows: tuple[OutcomeObservation, ...]) -> Decimal | None:
    values = tuple(
        item.realised_return_pct
        for item in rows
        if item.realised_return_pct is not None
    )
    return None if not values else _q(sum(values, Decimal("0")) / Decimal(len(values)))


def _entry_rate(rows: tuple[OutcomeObservation, ...]) -> Decimal | None:
    if not rows:
        return None
    return _q(
        Decimal(sum(1 for item in rows if item.entry_achieved))
        / Decimal(len(rows))
        * Decimal("100")
    )


def _unknown(
    drift_id: str, dimension: str, baseline: int, recent: int
) -> DriftAssessment:
    return DriftAssessment(
        drift_id=drift_id,
        dimension=dimension,
        baseline_count=baseline,
        recent_count=recent,
        baseline_value=None,
        recent_value=None,
        absolute_change=None,
        status=DriftStatus.UNKNOWN,
        confidence=LearningConfidence.INSUFFICIENT,
        evidence=("Insufficient completed outcomes for two guarded time segments.",),
    )


def _confidence(segment: int) -> LearningConfidence:
    if segment < 10:
        return LearningConfidence.INSUFFICIENT
    if segment < 20:
        return LearningConfidence.LOW
    if segment < 50:
        return LearningConfidence.MEDIUM
    return LearningConfidence.HIGH


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = ["ConceptDriftEngine"]
