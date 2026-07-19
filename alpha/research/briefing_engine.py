"""Executive briefing synthesis for the Institutional Research Director."""

from __future__ import annotations

from decimal import Decimal

from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EngineeringRoiReport,
    EvidenceQuality,
    ExecutiveResearchBrief,
    RankedBottleneck,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchRoadmap,
)
from alpha.research.roadmap_engine import first_actionable_item


class BriefingEngine:
    def build(
        self,
        *,
        diagnostics: tuple[DiagnosticEvidence, ...],
        bottlenecks: tuple[RankedBottleneck, ...],
        roadmap: ResearchRoadmap,
        roi: EngineeringRoiReport,
    ) -> ExecutiveResearchBrief:
        proven = next(
            (item for item in bottlenecks if item.status is BottleneckStatus.PROVEN),
            None,
        )
        unknown = next(
            (item for item in bottlenecks if item.status is BottleneckStatus.UNKNOWN),
            None,
        )
        highest_confidence = _highest_confidence_diagnostic(diagnostics)
        next_item = first_actionable_item(roadmap)
        return ExecutiveResearchBrief(
            current_replay_readiness=_replay_readiness(diagnostics),
            largest_proven_bottleneck=(
                "Unavailable"
                if proven is None
                else f"{proven.title}: {proven.evidence_summary}"
            ),
            largest_unknown=(
                f"{unknown.title}: {unknown.evidence_summary}"
                if unknown is not None
                else (
                    "Engineering impact remains UNKNOWN until controlled "
                    "experiments are completed."
                )
            ),
            highest_confidence_finding=(
                "Unavailable"
                if highest_confidence is None
                else (f"{highest_confidence.title}: {highest_confidence.finding}")
            ),
            highest_roi_completed_project=(
                roi.highest_roi_completed_project or "Unavailable"
            ),
            highest_priority_future_project=(
                "Unavailable" if next_item is None else next_item.title
            ),
            recommended_next_sprint=(
                "Collect additional diagnostic evidence."
                if next_item is None
                else (
                    f"{next_item.title} Supported by: "
                    f"{', '.join(next_item.supporting_diagnostics)}."
                )
            ),
            overall_research_confidence=_overall_confidence(diagnostics),
            diagnostics_considered=len(diagnostics),
            initial_evidence=_initial_evidence(diagnostics),
        )


def _replay_readiness(diagnostics: tuple[DiagnosticEvidence, ...]) -> str:
    evidence = next(
        (item for item in diagnostics if item.diagnostic_id == "replay-readiness"),
        None,
    )
    if evidence is None:
        return "Unavailable"
    metric = evidence.metric("replay.readiness")
    ready = evidence.metric("replay.ready_records")
    total = evidence.metric("replay.total_candidates")
    if (
        metric is None
        or not isinstance(metric.value, Decimal)
        or ready is None
        or not isinstance(ready.value, int)
        or total is None
        or not isinstance(total.value, int)
    ):
        return "Unavailable"
    return f"{metric.value * Decimal('100'):.2f}% ({ready.value}/{total.value})"


def _highest_confidence_diagnostic(
    diagnostics: tuple[DiagnosticEvidence, ...],
) -> DiagnosticEvidence | None:
    available = tuple(
        item
        for item in diagnostics
        if item.state in {DiagnosticState.AVAILABLE, DiagnosticState.PARTIAL}
    )
    if not available:
        return None
    maturity_rank = {
        ResearchMaturity.VALIDATED: 0,
        ResearchMaturity.PARTIAL: 1,
        ResearchMaturity.NASCENT: 2,
        ResearchMaturity.BLOCKED: 3,
        ResearchMaturity.UNKNOWN: 4,
    }
    confidence_rank = {
        ResearchConfidence.HIGH: 0,
        ResearchConfidence.MEDIUM: 1,
        ResearchConfidence.LOW: 2,
        ResearchConfidence.UNKNOWN: 3,
    }
    quality_rank = {
        EvidenceQuality.HIGH: 0,
        EvidenceQuality.MEDIUM: 1,
        EvidenceQuality.LOW: 2,
        EvidenceQuality.UNKNOWN: 3,
    }
    return min(
        available,
        key=lambda item: (
            confidence_rank[item.confidence],
            quality_rank[item.evidence_quality],
            maturity_rank[item.maturity],
            item.diagnostic_id,
        ),
    )


def _overall_confidence(
    diagnostics: tuple[DiagnosticEvidence, ...],
) -> ResearchConfidence:
    if not diagnostics:
        return ResearchConfidence.UNKNOWN
    available = tuple(
        item
        for item in diagnostics
        if item.state in {DiagnosticState.AVAILABLE, DiagnosticState.PARTIAL}
    )
    if not available:
        return ResearchConfidence.UNKNOWN
    if len(available) * 2 < len(diagnostics):
        return ResearchConfidence.LOW
    high = sum(item.confidence is ResearchConfidence.HIGH for item in available)
    if len(available) == len(diagnostics) and high * 4 >= len(available) * 3:
        return ResearchConfidence.HIGH
    return ResearchConfidence.MEDIUM


def _initial_evidence(
    diagnostics: tuple[DiagnosticEvidence, ...],
) -> tuple[ResearchMetric, ...]:
    metric_ids = (
        "approval.strict.precision",
        "approval.raw.precision",
        "directional.buy_precision",
        "directional.recommendation_auc",
        "replay.readiness",
        "identity.coverage",
        "corporate_action.coverage",
        "entry_timing.preferred_success_rate",
        "market_regime.balanced_accuracy",
        "point_in_time.sector_coverage",
    )
    index = {
        metric.metric_id: metric
        for diagnostic in diagnostics
        for metric in diagnostic.metrics
    }
    return tuple(index[metric_id] for metric_id in metric_ids if metric_id in index)


__all__ = ["BriefingEngine"]
