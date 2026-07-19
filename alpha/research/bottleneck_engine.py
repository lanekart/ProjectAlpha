"""Evidence-only engineering bottleneck ranking."""

from __future__ import annotations

from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EngineeringComplexity,
    EvidenceQuality,
    MetricAvailability,
    RankedBottleneck,
    ResearchConfidence,
    ResearchMaturity,
    RoadmapPriority,
)


class BottleneckEngine:
    """Rank native diagnostic findings without estimating financial gain."""

    def rank(
        self,
        diagnostics: tuple[DiagnosticEvidence, ...],
    ) -> tuple[RankedBottleneck, ...]:
        ranked = tuple(self._classify(item) for item in diagnostics)
        return tuple(sorted(ranked, key=_rank_key))

    def _classify(self, evidence: DiagnosticEvidence) -> RankedBottleneck:
        status = (
            BottleneckStatus.UNKNOWN
            if evidence.state in {DiagnosticState.UNAVAILABLE, DiagnosticState.FAILED}
            or any(
                metric.availability is MetricAvailability.INVALID
                for metric in evidence.metrics
            )
            else evidence.bottleneck_status
        )
        return RankedBottleneck(
            bottleneck_id=f"{evidence.diagnostic_id}-bottleneck",
            subsystem=evidence.subsystem,
            title=evidence.title,
            status=status,
            current_maturity=evidence.maturity,
            evidence_quality=evidence.evidence_quality,
            confidence=evidence.confidence,
            dependencies=evidence.dependencies,
            engineering_complexity=_complexity(evidence.dependencies),
            priority=_priority(evidence, status),
            supporting_diagnostics=(evidence.diagnostic_id,),
            evidence_summary=evidence.finding,
            recommended_action=evidence.recommended_action,
        )


def _priority(
    evidence: DiagnosticEvidence,
    status: BottleneckStatus,
) -> RoadmapPriority:
    if status is not BottleneckStatus.PROVEN:
        return RoadmapPriority.DEFERRED
    if (
        evidence.confidence is ResearchConfidence.HIGH
        and evidence.evidence_quality is EvidenceQuality.HIGH
        and evidence.maturity in {ResearchMaturity.BLOCKED, ResearchMaturity.NASCENT}
    ):
        return RoadmapPriority.P0
    if (
        evidence.confidence in {ResearchConfidence.HIGH, ResearchConfidence.MEDIUM}
        and evidence.evidence_quality in {EvidenceQuality.HIGH, EvidenceQuality.MEDIUM}
        and evidence.maturity
        in {
            ResearchMaturity.BLOCKED,
            ResearchMaturity.NASCENT,
            ResearchMaturity.PARTIAL,
        }
    ):
        return RoadmapPriority.P1
    return RoadmapPriority.P2


def _complexity(dependencies: tuple[str, ...]) -> EngineeringComplexity:
    if not dependencies:
        return EngineeringComplexity.LOW
    normalized = " ".join(dependencies).lower()
    external_tokens = ("authorized", "external", "licensed", "corporate-action")
    if any(token in normalized for token in external_tokens):
        return EngineeringComplexity.HIGH
    if len(dependencies) >= 2:
        return EngineeringComplexity.MEDIUM
    return EngineeringComplexity.LOW


def _rank_key(
    item: RankedBottleneck,
) -> tuple[int, int, int, int, str]:
    priority = {
        RoadmapPriority.P0: 0,
        RoadmapPriority.P1: 1,
        RoadmapPriority.P2: 2,
        RoadmapPriority.DEFERRED: 3,
    }
    confidence = {
        ResearchConfidence.HIGH: 0,
        ResearchConfidence.MEDIUM: 1,
        ResearchConfidence.LOW: 2,
        ResearchConfidence.UNKNOWN: 3,
    }
    evidence = {
        EvidenceQuality.HIGH: 0,
        EvidenceQuality.MEDIUM: 1,
        EvidenceQuality.LOW: 2,
        EvidenceQuality.UNKNOWN: 3,
    }
    maturity = {
        ResearchMaturity.BLOCKED: 0,
        ResearchMaturity.NASCENT: 1,
        ResearchMaturity.PARTIAL: 2,
        ResearchMaturity.VALIDATED: 3,
        ResearchMaturity.UNKNOWN: 4,
    }
    return (
        priority[item.priority],
        confidence[item.confidence],
        evidence[item.evidence_quality],
        maturity[item.current_maturity],
        item.bottleneck_id,
    )


__all__ = ["BottleneckEngine"]
