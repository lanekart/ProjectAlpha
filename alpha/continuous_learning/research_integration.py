from __future__ import annotations

from alpha.continuous_learning.continuous_learning_engine import (
    ContinuousLearningEngine,
)
from alpha.research.diagnostic_registry import CallableDiagnosticPlugin
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="continuous-learning-evidence",
            title="Continuous forward learning evidence",
            subsystem=ResearchSubsystem.CONTINUOUS_LEARNING,
            source_module="alpha.continuous_learning.learning_registry",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    report = ContinuousLearningEngine.from_paths().report(collect_first=False)
    observations = report.outcomes
    if not observations:
        return DiagnosticEvidence(
            diagnostic_id="continuous-learning-evidence",
            title="Continuous forward learning evidence",
            subsystem=ResearchSubsystem.CONTINUOUS_LEARNING,
            source_module="alpha.continuous_learning.learning_registry",
            source_version="continuous-learning-v1",
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No immutable continuous-learning observations are registered.",
            recommended_action="Run alpha learning collect.",
        )
    calibration = report.calibration
    health = report.strategy_health
    drifts = report.drifts
    completed = calibration.completed_predictions
    confidence = (
        ResearchConfidence.LOW
        if completed < 30
        else ResearchConfidence.MEDIUM
        if completed < 50
        else ResearchConfidence.HIGH
    )
    provenance = MetricProvenance(
        source="continuous learning registry",
        definition=(
            "Latest immutable observation per recommendation, with analytical "
            "eligibility requiring current source provenance"
        ),
        population="provenance-verifiable frozen recommendation outcomes",
        version="continuous-learning-v1",
    )
    metrics = (
        ResearchMetric(
            metric_id="continuous_learning.recommendations",
            label="Tracked frozen recommendations",
            value=len(observations),
            unit="count",
            provenance=provenance,
        ),
        ResearchMetric(
            metric_id="continuous_learning.completed_predictions",
            label="Resolved predictions",
            value=completed,
            unit="count",
            provenance=provenance,
        ),
        ResearchMetric(
            metric_id="continuous_learning.eligible_recommendations",
            label="Analytically eligible recommendations",
            value=report.analytically_eligible_recommendations,
            unit="count",
            provenance=provenance,
        ),
        ResearchMetric(
            metric_id="continuous_learning.quarantined_recommendations",
            label="Quarantined historical recommendations",
            value=report.quarantined_recommendations,
            unit="count",
            provenance=provenance,
        ),
        ResearchMetric(
            metric_id="continuous_learning.calibration_status",
            label="Confidence calibration status",
            value=calibration.status,
            unit="classification",
            provenance=provenance,
        ),
        ResearchMetric(
            metric_id="continuous_learning.largest_drift",
            label="Largest observed concept drift",
            value=";".join(sorted({item.status.value for item in drifts})),
            unit="classification",
            provenance=provenance,
        ),
    )
    needs_evidence = completed < 20
    return DiagnosticEvidence(
        diagnostic_id="continuous-learning-evidence",
        title="Continuous forward learning evidence",
        subsystem=ResearchSubsystem.CONTINUOUS_LEARNING,
        source_module="alpha.continuous_learning.learning_registry",
        source_version="continuous-learning-v1",
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.NASCENT
        if needs_evidence
        else ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.LOW
        if needs_evidence
        else EvidenceQuality.MEDIUM,
        confidence=confidence,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if needs_evidence
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=metrics,
        finding=(
            f"Tracked {len(observations)} recommendations; "
            f"eligible={report.analytically_eligible_recommendations}; "
            f"quarantined={report.quarantined_recommendations}; "
            f"resolved predictions={completed}; strategy groups={len(health)}; "
            f"calibration={calibration.status}."
        ),
        recommended_action=(
            "Mature immutable entry, exit, return, MFE, MAE, regime, sector, "
            "volatility, and liquidity outcomes before policy research."
        ),
        dependencies=("immutable forward recommendation outcomes",),
        limitations=(
            "Continuous learning evidence is advisory and is not measured "
            "deployment ROI.",
            "Registry observations without current source provenance are preserved "
            "but quarantined from analytical calculations.",
        ),
    )


__all__ = ["research_diagnostic_plugins"]
