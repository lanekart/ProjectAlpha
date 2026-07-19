from __future__ import annotations

from alpha.autonomous_loop.models import AUTONOMOUS_LOOP_SCHEMA_VERSION, RunStage
from alpha.autonomous_loop.registry import AutonomousLoopRegistry
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
            diagnostic_id="autonomous-decision-evidence-loop",
            title="Autonomous decision and evidence loop",
            subsystem=ResearchSubsystem.AUTONOMOUS_LOOP,
            source_module="alpha.autonomous_loop.registry",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    store = AutonomousLoopRegistry()
    schedules = store.schedules()
    events = store.run_events()
    decisions = store.decisions()
    resolutions = store.resolutions()
    completed = {item.run_id for item in events if item.stage is RunStage.COMPLETED}
    resolved_ids = {item.decision_id for item in resolutions}
    if not schedules:
        return DiagnosticEvidence(
            diagnostic_id="autonomous-decision-evidence-loop",
            title="Autonomous decision and evidence loop",
            subsystem=ResearchSubsystem.AUTONOMOUS_LOOP,
            source_module="alpha.autonomous_loop.registry",
            source_version=AUTONOMOUS_LOOP_SCHEMA_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No autonomous schedule is registered.",
            recommended_action="Run alpha autonomous bootstrap, then schedule tick.",
        )
    provenance = MetricProvenance(
        source="Autonomous loop immutable registry",
        definition="Append-only scheduled forward decision evidence",
        population="FORWARD_OBSERVED decisions only",
        version=AUTONOMOUS_LOOP_SCHEMA_VERSION,
    )
    unresolved = sum(1 for item in decisions if item.decision_id not in resolved_ids)
    return DiagnosticEvidence(
        diagnostic_id="autonomous-decision-evidence-loop",
        title="Autonomous decision and evidence loop",
        subsystem=ResearchSubsystem.AUTONOMOUS_LOOP,
        source_module="alpha.autonomous_loop.registry",
        source_version=AUTONOMOUS_LOOP_SCHEMA_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=(
            ResearchMaturity.PARTIAL if resolutions else ResearchMaturity.NASCENT
        ),
        evidence_quality=(
            EvidenceQuality.LOW if decisions else EvidenceQuality.UNKNOWN
        ),
        confidence=(
            ResearchConfidence.LOW if resolutions else ResearchConfidence.UNKNOWN
        ),
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if not resolutions or unresolved
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=(
            ResearchMetric(
                metric_id="autonomous.completed_runs",
                label="Completed scheduled runs",
                value=len(completed),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="autonomous.frozen_decisions",
                label="Frozen decisions",
                value=len(decisions),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="autonomous.resolved_decisions",
                label="Resolved decisions",
                value=len(resolutions),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="autonomous.forward_dna",
                label="Forward-observed DNA observations",
                value=len(store.forward_dna()),
                unit="count",
                provenance=provenance,
            ),
        ),
        finding=(
            f"Completed runs={len(completed)}; frozen decisions={len(decisions)}; "
            f"resolved={len(resolutions)}; unresolved={unresolved}."
        ),
        recommended_action=(
            "Continue idempotent scheduled collection until outcome, calibration, "
            "and DNA cohorts mature."
        ),
        dependencies=(
            "fresh persisted market data",
            "scheduled operator invocation",
            "immutable forward registry",
        ),
        limitations=(
            "No broker orders or unattended capital deployment are permitted.",
            "No hypothesis can mutate production policy.",
        ),
    )


__all__ = ["research_diagnostic_plugins"]
