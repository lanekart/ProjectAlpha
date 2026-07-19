from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from alpha.canonical_integrity_audit.exports import load_integrity_report_payload
from alpha.canonical_integrity_audit.models import (
    INTEGRITY_AUDIT_VERSION,
    CanonicalIntegrityAuditReport,
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


def record_integrity_experiment(
    report: CanonicalIntegrityAuditReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    provenance = _provenance(report.audit_id)
    summary = report.summary
    metrics = (
        _metric(
            "integrity.runtime_failure_rate",
            "Runtime failure rate after repair",
            _rate(
                report.runtime_replay.after_failure_days,
                max(report.runtime_replay.before_failure_days, 1),
            ),
            "ratio",
            provenance,
        ),
        _metric(
            "integrity.pine_parity_rate",
            "Exact or semantic Pine parity rate",
            summary.semantic_parity_rate,
            "ratio",
            provenance,
        ),
        _metric(
            "integrity.opportunity_capture_rate",
            "Major-opportunity capture rate",
            _rate(
                summary.captured,
                summary.major_opportunities,
            ),
            "ratio",
            provenance,
        ),
        _metric(
            "integrity.partial_capture_rate",
            "Major-opportunity partial capture rate",
            _rate(
                summary.partially_captured,
                summary.major_opportunities,
            ),
            "ratio",
            provenance,
        ),
        _metric(
            "integrity.miss_rate",
            "Major-opportunity miss rate",
            _rate(
                summary.missed,
                summary.major_opportunities,
            ),
            "ratio",
            provenance,
        ),
        _metric(
            "integrity.runtime_blocked_opportunities",
            "Runtime-blocked opportunities",
            summary.runtime_blocked,
            "count",
            provenance,
        ),
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=_experiment_id(report),
        title="Canonical Runtime Integrity and Opportunity Attribution Audit",
        subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
        experiment_date=report.generated_at.date(),
        purpose=(
            "Explain canonical runtime failures, TradingView divergence, and "
            "major-opportunity loss without changing strategy or approval policy."
        ),
        evidence_sources=(
            "canonical integrity audit artifacts",
            "ACU-1 before/after artifacts",
            "legacy daily_prices DuckDB",
            "TradingView trade CSV when supplied",
        ),
        baseline=(),
        treatment=metrics,
        metrics=tuple(item.metric_id for item in metrics),
        statistical_confidence=ResearchConfidence.MEDIUM,
        decision=ExperimentDecision.INCONCLUSIVE,
        status=ExperimentStatus.COMPLETED,
        findings=(
            f"primary_bottleneck={summary.primary_bottleneck.value}",
            f"runtime_days={report.runtime_replay.before_failure_days}->{report.runtime_replay.after_failure_days}",
            f"major_opportunities={summary.major_opportunities}",
        ),
        lessons_learned=(
            "TradingView parity is unavailable without exact trade-level CSV evidence.",
            "Legacy price and identity evidence remains provisional.",
            "No production policy, threshold, weight, or strategy was changed.",
        ),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="canonical-runtime-parity-opportunity-audit",
            title="Canonical runtime, parity, and opportunity integrity",
            subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
            source_module="alpha.canonical_integrity_audit",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    try:
        payload = load_integrity_report_payload()
    except (FileNotFoundError, ValueError):
        return DiagnosticEvidence(
            diagnostic_id="canonical-runtime-parity-opportunity-audit",
            title="Canonical runtime, parity, and opportunity integrity",
            subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
            source_module="alpha.canonical_integrity_audit",
            source_version=INTEGRITY_AUDIT_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed canonical integrity audit is available.",
            recommended_action="Run `alpha integrity-audit report`.",
        )
    summary = _mapping(payload.get("summary"))
    replay = _mapping(payload.get("runtime_replay"))
    provenance = _provenance(str(payload.get("audit_id", "UNKNOWN")))
    opportunities = _integer(summary.get("major_opportunities"))
    missed = _integer(summary.get("missed"))
    runtime_before = _integer(replay.get("before_failure_days"))
    runtime_after = _integer(replay.get("after_failure_days"))
    return DiagnosticEvidence(
        diagnostic_id="canonical-runtime-parity-opportunity-audit",
        title="Canonical runtime, parity, and opportunity integrity",
        subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
        source_module="alpha.canonical_integrity_audit",
        source_version=INTEGRITY_AUDIT_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.MEDIUM,
        confidence=ResearchConfidence.MEDIUM,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if runtime_before > runtime_after or missed
            else BottleneckStatus.UNKNOWN
        ),
        metrics=(
            _metric(
                "integrity.runtime_failure_rate",
                "Runtime failure rate after repair",
                _rate(runtime_after, max(runtime_before, 1)),
                "ratio",
                provenance,
            ),
            _metric(
                "integrity.pine_parity_rate",
                "Exact or semantic Pine parity rate",
                _optional_decimal(summary.get("semantic_parity_rate")),
                "ratio",
                provenance,
            ),
            _metric(
                "integrity.opportunity_capture_rate",
                "Major-opportunity capture rate",
                _rate(_integer(summary.get("captured")), opportunities),
                "ratio",
                provenance,
            ),
            _metric(
                "integrity.partial_capture_rate",
                "Major-opportunity partial capture rate",
                _rate(_integer(summary.get("partially_captured")), opportunities),
                "ratio",
                provenance,
            ),
            _metric(
                "integrity.miss_rate",
                "Major-opportunity miss rate",
                _rate(missed, opportunities),
                "ratio",
                provenance,
            ),
            _metric(
                "integrity.runtime_blocked_opportunities",
                "Runtime-blocked opportunities",
                _integer(summary.get("runtime_blocked")),
                "count",
                provenance,
            ),
        ),
        finding=(
            f"Runtime failures changed from {runtime_before} to {runtime_after}; "
            f"{missed} of {opportunities} major events were missed."
        ),
        recommended_action=(
            "Investigate the highest-count evidenced divergence stage; do not "
            "change policy until authoritative data and Pine CSV evidence agree."
        ),
        limitations=(
            "LEGACY_DATASET is provisional.",
            "TradingView is a secondary validator.",
            "Production influence is false.",
        ),
    )


def _provenance(population: str) -> MetricProvenance:
    return MetricProvenance(
        source="CanonicalIntegrityAuditEngine.run",
        definition=(
            "Frozen canonical runtime, parity, and major-opportunity attribution"
        ),
        population=population,
        version=INTEGRITY_AUDIT_VERSION,
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


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("integrity diagnostic object is invalid")
    return {str(key): item for key, item in value.items()}


def _integer(value: object) -> int:
    return int(str(value or 0))


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _experiment_id(report: CanonicalIntegrityAuditReport) -> str:
    payload = json.dumps(
        {
            "policy": to_primitive(report.policy),
            "runtime_replay": to_primitive(report.runtime_replay),
            "summary": to_primitive(report.summary),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{report.audit_id}|evidence-{digest}"


__all__ = ["record_integrity_experiment", "research_diagnostic_plugins"]
