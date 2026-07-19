from __future__ import annotations

from decimal import Decimal

from alpha.research.diagnostic_registry import CallableDiagnosticPlugin
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    MetricAvailability,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.setup_discovery.exports import load_setup_discovery_summary
from alpha.setup_discovery.models import SDE_VERSION

DIAGNOSTIC_ID = "setup-discovery-evidence"


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Unsupported setup and lookback evidence",
            subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
            source_module="alpha.setup_discovery",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    try:
        payload = load_setup_discovery_summary()
    except (FileNotFoundError, ValueError):
        return DiagnosticEvidence(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Unsupported setup and lookback evidence",
            subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
            source_module="alpha.setup_discovery",
            source_version=SDE_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed Setup Discovery evidence artifact is available.",
            recommended_action="Run `alpha setup-discovery report`.",
        )
    summary = _mapping(payload["summary"])
    manifest = _mapping(payload["manifest"])
    unsupported = _integer(summary.get("unsupported_cases"))
    claimed = _integer(summary.get("lookback_cases_claimed"))
    confirmed = _integer(summary.get("lookback_cases_confirmed"))
    provenance = MetricProvenance(
        source="SetupDiscoveryEvidenceEngine.run",
        definition="Causal setup clustering and expanded-lookback proof",
        population=str(manifest.get("source_audit_id", "UNKNOWN")),
        version=SDE_VERSION,
    )
    metrics = (
        _metric(
            "setup_discovery.unsupported_cases",
            "Unsupported setup cases",
            unsupported,
            "count",
            provenance,
        ),
        _metric(
            "setup_discovery.families",
            "Distinct causal setup families",
            _integer(summary.get("clusters_selected")),
            "count",
            provenance,
        ),
        _metric(
            "setup_discovery.clustered_cases",
            "Unsupported cases with clusterable point-in-time history",
            _integer(summary.get("unsupported_cases_clustered")),
            "count",
            provenance,
        ),
        _metric(
            "setup_discovery.top_three_share",
            "Unsupported cases explained by three largest families",
            _decimal(summary.get("top_three_case_share")),
            "ratio",
            provenance,
        ),
        _metric(
            "setup_discovery.lookback_proof_rate",
            "Claimed lookback mismatches surviving causal proof",
            None if claimed == 0 else Decimal(confirmed) / Decimal(claimed),
            "ratio",
            provenance,
        ),
    )
    confidence = str(summary.get("overall_evidence_confidence", "UNKNOWN"))
    return DiagnosticEvidence(
        diagnostic_id=DIAGNOSTIC_ID,
        title="Unsupported setup and lookback evidence",
        subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
        source_module="alpha.setup_discovery",
        source_version=SDE_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=_quality(confidence),
        confidence=_confidence(confidence),
        bottleneck_status=(
            BottleneckStatus.PROVEN if unsupported > 0 else BottleneckStatus.UNKNOWN
        ),
        metrics=metrics,
        finding=(
            f"{summary.get('clusters_selected')} causal families explain {unsupported} "
            f"unsupported cases; {confirmed} of {claimed} lookback claims survived "
            "proof."
        ),
        recommended_action=(
            "Use the recommendation matrix to select isolated Strategy Lab research; "
            "do not alter production setup or lookback policy from this diagnostic."
        ),
        limitations=(
            "Legacy market data and frozen candidate-research artifacts remain "
            "provisional.",
            "Future outcomes describe frozen clusters but never create labels.",
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


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("setup discovery artifact is invalid")
    return {str(key): item for key, item in value.items()}


def _integer(value: object) -> int:
    return int(str(value or 0))


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _quality(value: str) -> EvidenceQuality:
    return {
        "HIGH": EvidenceQuality.HIGH,
        "MODERATE": EvidenceQuality.MEDIUM,
        "LOW": EvidenceQuality.LOW,
    }.get(value, EvidenceQuality.UNKNOWN)


def _confidence(value: str) -> ResearchConfidence:
    return {
        "HIGH": ResearchConfidence.HIGH,
        "MODERATE": ResearchConfidence.MEDIUM,
        "LOW": ResearchConfidence.LOW,
    }.get(value, ResearchConfidence.UNKNOWN)


__all__ = ["research_diagnostic_plugins"]
