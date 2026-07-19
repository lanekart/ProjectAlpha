from __future__ import annotations

from alpha.market_truth.market_truth_engine import MarketTruthEngine
from alpha.market_truth.models import MARKET_TRUTH_SCHEMA_VERSION
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
            diagnostic_id="market-truth-engine",
            title="Market Truth Engine",
            subsystem=ResearchSubsystem.MARKET_TRUTH,
            source_module="alpha.market_truth.market_truth_engine",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    engine = MarketTruthEngine.default()
    report = engine.report()
    provenance = MetricProvenance(
        source="Market Truth Engine provider and cache registry",
        definition="Configured market-data providers and versioned cache state",
        population="MTE provider plugins only",
        version=MARKET_TRUTH_SCHEMA_VERSION,
    )
    operational = report.healthy_providers + report.degraded_providers
    return DiagnosticEvidence(
        diagnostic_id="market-truth-engine",
        title="Market Truth Engine",
        subsystem=ResearchSubsystem.MARKET_TRUTH,
        source_module="alpha.market_truth.market_truth_engine",
        source_version=MARKET_TRUTH_SCHEMA_VERSION,
        state=(DiagnosticState.AVAILABLE if operational else DiagnosticState.PARTIAL),
        maturity=ResearchMaturity.NASCENT,
        evidence_quality=(
            EvidenceQuality.MEDIUM if operational else EvidenceQuality.UNKNOWN
        ),
        confidence=(
            ResearchConfidence.MEDIUM if operational else ResearchConfidence.UNKNOWN
        ),
        bottleneck_status=(
            BottleneckStatus.NO_MATERIAL_GAP if operational else BottleneckStatus.PROVEN
        ),
        metrics=(
            ResearchMetric(
                metric_id="market_truth.providers",
                label="Registered providers",
                value=report.provider_count,
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_truth.configured",
                label="Configured providers",
                value=report.configured_providers,
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_truth.operational",
                label="Healthy or degraded providers",
                value=operational,
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_truth.cache_entries",
                label="Versioned cache entries",
                value=report.cached_datasets,
                unit="count",
                provenance=provenance,
            ),
        ),
        finding=(
            f"Providers={report.provider_count}; "
            f"configured={report.configured_providers}; "
            f"operational={operational}; cache entries={report.cached_datasets}."
        ),
        recommended_action=(
            "Configure at least one authoritative historical source and one licensed "
            "live source, then mature provider health evidence."
            if not operational
            else "Continue quality, completeness, and failover monitoring."
        ),
        dependencies=("authoritative provider access", "versioned local cache"),
        limitations=(
            "MTE does not place orders or change recommendation policy.",
            "Unconfigured sources return NO_DATA rather than synthetic records.",
        ),
    )


__all__ = ["research_diagnostic_plugins"]
