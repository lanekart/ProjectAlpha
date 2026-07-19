from __future__ import annotations

from decimal import Decimal

from alpha.canonical_universe_audit.exporting import load_audit_payload
from alpha.canonical_universe_audit.models import (
    ACU_SCHEMA_VERSION,
    CanonicalUniverseAuditReport,
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


def record_acu_experiment(
    report: CanonicalUniverseAuditReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    provenance = MetricProvenance(
        source="CanonicalUniverseAuditEngine.run",
        definition="Frozen current-Alpha whole-universe opportunity funnel",
        population=(
            f"LEGACY_DATASET {report.daily[0].observed_on.isoformat()} through "
            f"{report.daily[-1].observed_on.isoformat()}"
        ),
        version=ACU_SCHEMA_VERSION,
    )
    summary = report.executive
    metrics = (
        _metric(
            "acu.sessions",
            "Sessions audited",
            summary.total_sessions,
            "count",
            provenance,
        ),
        _metric(
            "acu.technical_candidates",
            "Technical candidates",
            summary.total_candidates,
            "count",
            provenance,
        ),
        _metric(
            "acu.institutional_approvals",
            "Institutional approvals",
            summary.total_institutional_approvals,
            "count",
            provenance,
        ),
        _metric(
            "acu.portfolio_eligible",
            "Portfolio-eligible opportunities",
            summary.total_portfolio_eligible,
            "count",
            provenance,
        ),
        _metric(
            "acu.canonical_runtime_failure_days",
            "Canonical runtime failure days",
            summary.canonical_runtime_failure_days,
            "count",
            provenance,
        ),
        _metric(
            "acu.scored_candidates",
            "Candidates with final canonical scores",
            summary.scored_candidates,
            "count",
            provenance,
        ),
        _metric(
            "acu.average_opportunities_per_day",
            "Average opportunities per day",
            summary.average_opportunities_per_day,
            "count_per_day",
            provenance,
        ),
        _metric(
            "acu.win_rate",
            "Completed approval-candidate plan win rate",
            summary.win_rate,
            "ratio",
            provenance,
        ),
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=report.audit_id,
        title="Alpha Canonical Universe Opportunity Audit",
        subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
        experiment_date=report.daily[-1].observed_on,
        purpose=(
            "Measure current Alpha opportunity frequency, rejection gates, "
            "capacity, and historical trade-plan outcomes without policy mutation."
        ),
        evidence_sources=(
            "legacy daily_prices DuckDB",
            "ALPHA_CANONICAL_v1.0 recommendation pipeline",
            "current institutional decision and portfolio gates",
        ),
        baseline=(),
        treatment=metrics,
        metrics=tuple(item.metric_id for item in metrics),
        statistical_confidence=ResearchConfidence.MEDIUM,
        decision=ExperimentDecision.INCONCLUSIVE,
        status=ExperimentStatus.COMPLETED,
        findings=(
            f"institutional_approvals={summary.total_institutional_approvals}",
            f"portfolio_eligible={summary.total_portfolio_eligible}",
            f"largest_gate={summary.largest_gate}",
        ),
        lessons_learned=(
            "Evidence remains provisional until an authoritative market warehouse "
            "repeats the audit.",
            "No adaptive or production policy update was performed.",
        ),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="canonical-universe-opportunity-audit",
            title="Canonical universe opportunity capacity",
            subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
            source_module="alpha.canonical_universe_audit",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    try:
        payload = load_audit_payload()
    except (FileNotFoundError, ValueError):
        return DiagnosticEvidence(
            diagnostic_id="canonical-universe-opportunity-audit",
            title="Canonical universe opportunity capacity",
            subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
            source_module="alpha.canonical_universe_audit",
            source_version=ACU_SCHEMA_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed ACU artifact is available.",
            recommended_action="Run `alpha acu run` on the frozen legacy dataset.",
        )
    executive = _mapping(payload.get("executive"), "ACU executive")
    dataset = _mapping(payload.get("dataset"), "ACU dataset")
    provenance = MetricProvenance(
        source="ACU opportunity_capacity.json",
        definition="Frozen current-Alpha whole-universe opportunity funnel",
        population=str(payload.get("audit_id", "unknown audit")),
        version=ACU_SCHEMA_VERSION,
    )
    approvals = _integer(executive.get("total_institutional_approvals"))
    sessions = _integer(executive.get("total_sessions"))
    return DiagnosticEvidence(
        diagnostic_id="canonical-universe-opportunity-audit",
        title="Canonical universe opportunity capacity",
        subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
        source_module="alpha.canonical_universe_audit",
        source_version=ACU_SCHEMA_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.MEDIUM,
        confidence=ResearchConfidence.MEDIUM,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if sessions > 0 and approvals == 0
            else BottleneckStatus.UNKNOWN
        ),
        metrics=(
            _metric("acu.sessions", "Sessions audited", sessions, "count", provenance),
            _metric(
                "acu.institutional_approvals",
                "Institutional approvals",
                approvals,
                "count",
                provenance,
            ),
            _metric(
                "acu.dataset_rows",
                "Legacy dataset rows",
                _integer(dataset.get("rows")),
                "count",
                provenance,
            ),
        ),
        finding=(
            f"The frozen engine produced {approvals} institutional approvals across "
            f"{sessions} audited sessions."
        ),
        recommended_action=(
            "Use gate attribution and capacity evidence to select the next offline "
            "research experiment; do not mutate production policy."
        ),
        limitations=(
            "PROVISIONAL / NOT AUTHORITATIVE / LEGACY_DATASET",
            "Sector, free-float, industry, theme, and market-cap history are missing.",
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


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an ACU integer")
    return int(str(value))


__all__ = ["record_acu_experiment", "research_diagnostic_plugins"]
