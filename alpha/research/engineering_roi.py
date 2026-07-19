"""Measured and estimated engineering ROI kept as separate concepts."""

from __future__ import annotations

from decimal import Decimal

from alpha.research.models import (
    EngineeringRoiReport,
    EstimatedRoiOpportunity,
    ExperimentStatus,
    MeasuredRoiDelta,
    RankedBottleneck,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMetric,
)


class EngineeringRoiEngine:
    """Compute observed experiment deltas without inventing expected gains."""

    def assess(
        self,
        *,
        experiments: tuple[RegisteredResearchExperiment, ...],
        bottlenecks: tuple[RankedBottleneck, ...],
    ) -> EngineeringRoiReport:
        completed = tuple(
            experiment
            for experiment in experiments
            if experiment.status is ExperimentStatus.COMPLETED
        )
        measured = tuple(
            delta for experiment in completed for delta in _measured_deltas(experiment)
        )
        estimated = tuple(
            EstimatedRoiOpportunity(
                bottleneck_id=item.bottleneck_id,
                subsystem=item.subsystem,
                estimated_gain=None,
                confidence=ResearchConfidence.UNKNOWN,
                explanation=(
                    "Estimated gain is UNKNOWN until a completed controlled "
                    "experiment measures a comparable outcome."
                ),
                supporting_diagnostics=item.supporting_diagnostics,
            )
            for item in bottlenecks
            if item.status.value == "PROVEN"
        )
        highest = _highest_comparable_engineering_roi(measured)
        return EngineeringRoiReport(
            measured=tuple(
                sorted(measured, key=lambda item: (item.experiment_id, item.metric_id))
            ),
            estimated=tuple(sorted(estimated, key=lambda item: item.bottleneck_id)),
            completed_experiments=len(completed),
            highest_roi_completed_project=highest,
            comparison_warning=(
                "Measured deltas are compared only when metric id, unit, source, "
                "definition, population, and version are identical. Estimated ROI "
                "is never combined with measured ROI."
            ),
        )


def _measured_deltas(
    experiment: RegisteredResearchExperiment,
) -> tuple[MeasuredRoiDelta, ...]:
    treatment = {metric.metric_id: metric for metric in experiment.treatment}
    deltas: list[MeasuredRoiDelta] = []
    for baseline in experiment.baseline:
        candidate = treatment.get(baseline.metric_id)
        if candidate is None or not baseline.comparable_with(candidate):
            continue
        baseline_value = _decimal_value(baseline)
        treatment_value = _decimal_value(candidate)
        if baseline_value is None or treatment_value is None:
            continue
        deltas.append(
            MeasuredRoiDelta(
                experiment_id=experiment.experiment_id,
                metric_id=baseline.metric_id,
                metric_label=baseline.label,
                baseline=baseline_value,
                treatment=treatment_value,
                absolute_change=treatment_value - baseline_value,
                unit=baseline.unit,
                confidence=experiment.statistical_confidence,
                provenance=baseline.provenance,
            )
        )
    return tuple(deltas)


def _decimal_value(metric: ResearchMetric) -> Decimal | None:
    value = metric.value
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None
    if isinstance(value, int):
        return Decimal(value)
    return value


def _highest_comparable_engineering_roi(
    measured: tuple[MeasuredRoiDelta, ...],
) -> str | None:
    roi = tuple(item for item in measured if item.metric_id == "engineering.roi")
    if not roi:
        return None
    first = roi[0]
    if any(
        item.unit != first.unit
        or item.provenance.comparison_key != first.provenance.comparison_key
        for item in roi
    ):
        return None
    return max(
        roi, key=lambda item: (item.absolute_change, item.experiment_id)
    ).experiment_id


__all__ = ["EngineeringRoiEngine"]
