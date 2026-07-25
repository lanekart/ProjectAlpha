"""Deterministic artifact projections for governed gate pipeline results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from alpha.decision_superiority.gate_pipeline import GatePipelineResult

GATE_CONCLUSION_FIELDS = (
    "gate_code",
    "economic_direction",
    "statistical_direction",
    "recommendation",
    "reason_code",
    "isolation_status",
    "production_influence",
)
EVIDENCE_SUMMARY_FIELDS = (
    "gate_code",
    "observed_blocked_count",
    "observed_resolved_count",
    "co_blocked_count",
    "isolated_sample_count",
    "isolated_resolved_count",
    "minimum_required",
    "evidence_strength",
    "sufficient",
    "confidence_status",
    "insufficiency_reason",
    "isolation_status",
    "production_influence",
)
CONFIDENCE_SUMMARY_FIELDS = (
    "gate_code",
    "mean_return_pct",
    "variance_return_pct",
    "standard_deviation_return_pct",
    "success_rate",
    "success_interval_lower",
    "success_interval_upper",
    "success_interval_method",
    "mean_interval_lower",
    "mean_interval_upper",
    "mean_interval_method",
    "isolation_status",
    "production_influence",
)
GATE_RECOMMENDATION_FIELDS = (
    "gate_code",
    "recommendation",
    "reason_code",
    "evidence_strength",
    "confidence_status",
    "isolated_net_gate_value",
    "isolation_status",
    "production_influence",
)


@dataclass(frozen=True, slots=True)
class GateArtifactRows:
    """Immutable deterministic projections for new DSI-001 artifacts."""

    conclusions: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    confidence: tuple[dict[str, object], ...]
    recommendations: tuple[dict[str, object], ...]


def build_gate_artifact_rows(
    pipelines_by_gate: Mapping[str, GatePipelineResult],
) -> GateArtifactRows:
    """Project canonical pipeline results into deterministic artifact rows."""
    conclusions: list[dict[str, object]] = []
    evidence_rows: list[dict[str, object]] = []
    confidence_rows: list[dict[str, object]] = []
    recommendation_rows: list[dict[str, object]] = []

    for gate_code, pipeline in sorted(pipelines_by_gate.items()):
        if gate_code != pipeline.gate_code:
            raise ValueError("pipeline mapping key must match pipeline gate_code")
        if pipeline.production_influence:
            raise ValueError("DSI artifacts must remain diagnostic-only")

        conclusion = pipeline.conclusion
        confidence = pipeline.confidence
        evidence = pipeline.evidence_strength
        success_interval = confidence.success_rate_interval
        mean_interval = confidence.mean_return_interval
        isolated_value: object = (
            pipeline.economic_value.net_gate_value
            if pipeline.distribution.resolved_count > 0
            else "UNAVAILABLE"
        )

        conclusions.append(
            {
                "gate_code": gate_code,
                "economic_direction": conclusion.economic_direction.value,
                "statistical_direction": conclusion.statistical_direction.value,
                "recommendation": conclusion.recommendation.value,
                "reason_code": conclusion.reason_code,
                "isolation_status": pipeline.isolation_status,
                "production_influence": False,
            }
        )
        evidence_rows.append(
            {
                "gate_code": gate_code,
                "observed_blocked_count": pipeline.observed_blocked_count,
                "observed_resolved_count": pipeline.observed_resolved_count,
                "co_blocked_count": pipeline.co_blocked_count,
                "isolated_sample_count": evidence.sample_count,
                "isolated_resolved_count": evidence.resolved_count,
                "minimum_required": evidence.minimum_required,
                "evidence_strength": evidence.level.value,
                "sufficient": evidence.sufficient,
                "confidence_status": confidence.status.value,
                "insufficiency_reason": confidence.insufficiency_reason,
                "isolation_status": pipeline.isolation_status,
                "production_influence": False,
            }
        )
        confidence_rows.append(
            {
                "gate_code": gate_code,
                "mean_return_pct": confidence.mean_return_pct,
                "variance_return_pct": confidence.variance_return_pct,
                "standard_deviation_return_pct": (
                    confidence.standard_deviation_return_pct
                ),
                "success_rate": (
                    confidence.success_rate
                    if confidence.success_rate is not None
                    else ""
                ),
                "success_interval_lower": (
                    success_interval.lower if success_interval is not None else ""
                ),
                "success_interval_upper": (
                    success_interval.upper if success_interval is not None else ""
                ),
                "success_interval_method": (
                    success_interval.method if success_interval is not None else ""
                ),
                "mean_interval_lower": (
                    mean_interval.lower if mean_interval is not None else ""
                ),
                "mean_interval_upper": (
                    mean_interval.upper if mean_interval is not None else ""
                ),
                "mean_interval_method": (
                    mean_interval.method if mean_interval is not None else ""
                ),
                "isolation_status": pipeline.isolation_status,
                "production_influence": False,
            }
        )
        recommendation_rows.append(
            {
                "gate_code": gate_code,
                "recommendation": conclusion.recommendation.value,
                "reason_code": conclusion.reason_code,
                "evidence_strength": evidence.level.value,
                "confidence_status": confidence.status.value,
                "isolated_net_gate_value": isolated_value,
                "isolation_status": pipeline.isolation_status,
                "production_influence": False,
            }
        )

    return GateArtifactRows(
        conclusions=tuple(conclusions),
        evidence=tuple(evidence_rows),
        confidence=tuple(confidence_rows),
        recommendations=tuple(recommendation_rows),
    )
