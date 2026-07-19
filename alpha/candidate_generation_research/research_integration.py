from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from alpha.candidate_generation_research.exports import (
    load_candidate_research_payload,
)
from alpha.candidate_generation_research.models import (
    RESEARCH_VERSION,
    CandidateResearchReport,
    to_primitive,
)
from alpha.research.diagnostic_registry import CallableDiagnosticPlugin
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    ExperimentDecision,
    ExperimentStatus,
    MetricAvailability,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.research.research_registry import ResearchExperimentRegistry

DIAGNOSTIC_ID = "candidate-generation-recovery-audit"


def record_candidate_research_experiment(
    report: CandidateResearchReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    provenance = _provenance(report.audit_id)
    summary = report.summary
    metrics = (
        _metric(
            "candidate_research.forward_moves",
            "Forward move events",
            summary.forward_move_events,
            "count",
            provenance,
        ),
        _metric(
            "candidate_research.tradable_events",
            "Events with point-in-time tradable onset",
            summary.tradable_event_count,
            "count",
            provenance,
        ),
        _metric(
            "candidate_research.tradable_share",
            "Future moves with a tradable onset",
            summary.future_moves_actually_tradable_share,
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.setup_recall",
            "Canonical setup recall on tradable events",
            summary.canonical_setup_recall,
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.candidate_recall",
            "Canonical candidate recall on tradable events",
            summary.canonical_candidate_recall,
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.median_delay",
            "Median canonical candidate delay",
            summary.median_candidate_delay,
            "sessions",
            provenance,
        ),
        _metric(
            "candidate_research.median_onset_to_peak",
            "Median point-in-time onset to outcome peak",
            summary.median_onset_to_peak_sessions,
            "sessions",
            provenance,
        ),
        _metric(
            "candidate_research.median_pre_entry_mae",
            "Median associated event adverse excursion before peak",
            summary.median_pre_entry_mae,
            "signed_return",
            provenance,
        ),
        _metric(
            "candidate_research.median_prospective_rr",
            "Median prospective reward/risk at onset",
            summary.median_prospective_rr,
            "R",
            provenance,
        ),
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=_experiment_id(report),
        title="Tradable Opportunity and Candidate Generation Recovery",
        subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
        experiment_date=report.generated_at.date(),
        purpose=(
            "Separate hindsight winners from point-in-time tradable onsets and "
            "measure canonical candidate-generation recall."
        ),
        evidence_sources=(
            "LEGACY_DATASET provisional daily OHLCV",
            "ALPHA_CANONICAL_v1.0 ACU artifacts",
            "TradingView trade-level CSV when supplied",
        ),
        baseline=(),
        treatment=metrics,
        metrics=tuple(item.metric_id for item in metrics),
        statistical_confidence=ResearchConfidence.MEDIUM,
        decision=(
            ExperimentDecision.ACCEPT
            if report.policy_proposal.status.value == "PROMOTE_TO_POLICY_REVIEW"
            else ExperimentDecision.INCONCLUSIVE
        ),
        status=ExperimentStatus.COMPLETED,
        findings=(
            f"tradable_event_share={summary.future_moves_actually_tradable_share}",
            f"canonical_candidate_recall={summary.canonical_candidate_recall}",
            f"best_validated_variant={summary.best_validated_variant}",
        ),
        lessons_learned=(
            "Future return remained an outcome label only.",
            "Holdout did not select the candidate variant.",
            "No production policy was changed.",
        ),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Tradable opportunity and candidate-generation recovery",
            subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
            source_module="alpha.candidate_generation_research",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    try:
        payload = load_candidate_research_payload()
    except (FileNotFoundError, ValueError):
        return DiagnosticEvidence(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Tradable opportunity and candidate-generation recovery",
            subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
            source_module="alpha.candidate_generation_research",
            source_version=RESEARCH_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed candidate-generation research artifact is available.",
            recommended_action="Run `alpha candidate-research report`.",
        )
    summary = _mapping(payload.get("summary"))
    provenance = _provenance(str(payload.get("audit_id", "UNKNOWN")))
    forward_moves = _integer(summary.get("forward_move_events"))
    tradable_events = _integer(summary.get("tradable_event_count"))
    candidate_recall = _decimal(summary.get("canonical_candidate_recall"))
    metrics = (
        _metric(
            "candidate_research.forward_moves",
            "Forward move events",
            forward_moves,
            "count",
            provenance,
        ),
        _metric(
            "candidate_research.tradable_events",
            "Events with point-in-time tradable onset",
            tradable_events,
            "count",
            provenance,
        ),
        _metric(
            "candidate_research.tradable_share",
            "Future moves with a tradable onset",
            _decimal(summary.get("future_moves_actually_tradable_share")),
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.setup_recall",
            "Canonical setup recall on tradable events",
            _decimal(summary.get("canonical_setup_recall")),
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.candidate_recall",
            "Canonical candidate recall on tradable events",
            candidate_recall,
            "ratio",
            provenance,
        ),
        _metric(
            "candidate_research.median_delay",
            "Median canonical candidate delay",
            _decimal(summary.get("median_candidate_delay")),
            "sessions",
            provenance,
        ),
        _metric(
            "candidate_research.median_onset_to_peak",
            "Median point-in-time onset to outcome peak",
            _decimal(summary.get("median_onset_to_peak_sessions")),
            "sessions",
            provenance,
        ),
        _metric(
            "candidate_research.median_pre_entry_mae",
            "Median associated event adverse excursion before peak",
            _decimal(summary.get("median_pre_entry_mae")),
            "signed_return",
            provenance,
        ),
        _metric(
            "candidate_research.median_prospective_rr",
            "Median prospective reward/risk at onset",
            _decimal(summary.get("median_prospective_rr")),
            "R",
            provenance,
        ),
    )
    return DiagnosticEvidence(
        diagnostic_id=DIAGNOSTIC_ID,
        title="Tradable opportunity and candidate-generation recovery",
        subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
        source_module="alpha.candidate_generation_research",
        source_version=RESEARCH_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.MEDIUM,
        confidence=ResearchConfidence.MEDIUM,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if candidate_recall is not None and candidate_recall < Decimal("0.50")
            else BottleneckStatus.UNKNOWN
        ),
        metrics=metrics,
        finding=(
            f"{tradable_events} of {forward_moves} forward moves had a point-in-time "
            f"tradable onset; canonical candidate recall was {candidate_recall}. "
            f"Largest setup blocker: {summary.get('primary_setup_blocker')}. "
            f"Largest timing blocker: {summary.get('primary_timing_blocker')}. "
            f"Best validated variant: {summary.get('best_validated_variant')}. "
            f"Kalyan: {summary.get('kalyan_classification')}; "
            f"PC Jeweller: {summary.get('pc_jeweller_classification')}."
        ),
        recommended_action=(
            "Next research question: can the largest setup vocabulary and timing "
            "blockers improve holdout expectancy without candidate explosion? "
            "Promote no candidate policy without validation and holdout evidence."
        ),
        limitations=(
            "LEGACY_DATASET is provisional.",
            "The frozen ACU artifact retains only the ranked candidate surface.",
            "Production influence is false.",
        ),
    )


def _metric(
    metric_id: str,
    label: str,
    value: int | Decimal | None,
    unit: str,
    provenance: MetricProvenance,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        provenance=provenance,
        availability=(
            MetricAvailability.NOT_ESTIMABLE
            if value is None
            else MetricAvailability.AVAILABLE
        ),
    )


def _provenance(population: str) -> MetricProvenance:
    return MetricProvenance(
        source="CandidateGenerationResearchEngine.run",
        definition="Point-in-time tradability and frozen canonical candidate trace",
        population=population,
        version=RESEARCH_VERSION,
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("candidate research summary is invalid")
    return {str(key): item for key, item in value.items()}


def _integer(value: object) -> int:
    return int(str(value or 0))


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _experiment_id(report: CandidateResearchReport) -> str:
    payload = json.dumps(
        {
            "manifest": to_primitive(report.manifest),
            "proposal": to_primitive(report.policy_proposal),
            "summary": to_primitive(report.summary),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"CANDIDATE-RESEARCH-{report.generated_at.date()}-{digest}"


__all__ = [
    "record_candidate_research_experiment",
    "research_diagnostic_plugins",
]
