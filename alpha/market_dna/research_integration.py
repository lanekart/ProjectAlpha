from __future__ import annotations

from alpha.market_dna.dna_registry import DNARegistry
from alpha.market_dna.models import MARKET_DNA_SCHEMA_VERSION, DNADiscoveryReport
from alpha.research.diagnostic_registry import CallableDiagnosticPlugin
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    ExperimentDecision,
    ExperimentStatus,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.research.research_registry import ResearchExperimentRegistry


def record_market_dna_experiment(
    report: DNADiscoveryReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    experiment = RegisteredResearchExperiment(
        experiment_id=report.report_id,
        title="Market DNA outcome-first discovery",
        subsystem=ResearchSubsystem.MARKET_DNA,
        experiment_date=report.generated_at.date(),
        purpose=(
            "Identify stable point-in-time characteristics associated with historical "
            "outcome cohorts without changing production behavior."
        ),
        evidence_sources=(
            "candidate_learning_ledger",
            "alpha.strategy_discovery",
            "alpha.market_dna.dna_registry",
        ),
        baseline=(),
        treatment=(),
        metrics=(
            "cohort enrichment",
            "effect size",
            "temporal stability",
            "concentration",
            "false-discovery adjustment",
        ),
        statistical_confidence=ResearchConfidence.LOW,
        decision=(
            ExperimentDecision.ACCEPT
            if report.hypotheses
            else ExperimentDecision.INCONCLUSIVE
        ),
        status=ExperimentStatus.COMPLETED,
        findings=(
            report.final_conclusion,
            f"Patterns tested: {len(report.patterns)}",
            f"Hypotheses generated: {len(report.hypotheses)}",
        ),
        lessons_learned=(report.highest_value_evidence_gap,),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="market-dna-discovery",
            title="Market DNA outcome-first discovery",
            subsystem=ResearchSubsystem.MARKET_DNA,
            source_module="alpha.market_dna.dna_registry",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    payload = DNARegistry().latest_payload()
    if payload is None:
        return DiagnosticEvidence(
            diagnostic_id="market-dna-discovery",
            title="Market DNA outcome-first discovery",
            subsystem=ResearchSubsystem.MARKET_DNA,
            source_module="alpha.market_dna.dna_registry",
            source_version=MARKET_DNA_SCHEMA_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No Market DNA report is registered.",
            recommended_action="Run alpha market-dna report.",
        )
    patterns = _rows(payload.get("patterns"))
    hypotheses = _rows(payload.get("hypotheses"))
    feature_audits = _rows(payload.get("feature_audits"))
    provenance = MetricProvenance(
        source="Market DNA immutable registry",
        definition="Latest bounded outcome-first discovery report",
        population=str(payload.get("dataset_version", "unknown")),
        version=MARKET_DNA_SCHEMA_VERSION,
    )
    return DiagnosticEvidence(
        diagnostic_id="market-dna-discovery",
        title="Market DNA outcome-first discovery",
        subsystem=ResearchSubsystem.MARKET_DNA,
        source_module="alpha.market_dna.dna_registry",
        source_version=MARKET_DNA_SCHEMA_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.BLOCKED,
        evidence_quality=EvidenceQuality.LOW,
        confidence=ResearchConfidence.LOW,
        bottleneck_status=BottleneckStatus.PROVEN,
        metrics=(
            ResearchMetric(
                metric_id="market_dna.patterns_tested",
                label="DNA patterns tested",
                value=len(patterns),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_dna.hypotheses_generated",
                label="Strategy hypotheses generated",
                value=len(hypotheses),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_dna.feature_audits",
                label="Feature audits",
                value=len(feature_audits),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="market_dna.final_conclusion",
                label="Market DNA conclusion",
                value=str(payload.get("final_conclusion", "UNKNOWN")),
                unit="classification",
                provenance=provenance,
            ),
        ),
        finding=(
            f"Latest outcome-first report tested {len(patterns)} patterns and "
            "generated "
            f"{len(hypotheses)} governed hypotheses; conclusion="
            f"{payload.get('final_conclusion', 'UNKNOWN')}."
        ),
        recommended_action=str(
            payload.get(
                "highest_value_evidence_gap",
                "Acquire authoritative completed outcomes.",
            )
        ),
        dependencies=(
            "authoritative completed outcomes",
            "corporate-action-complete chronological bars",
            "untouched holdout population",
        ),
        limitations=(
            "Reconstructed associations are not causal or measured forward ROI.",
            "Production influence is disabled.",
        ),
    )


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


__all__ = ["record_market_dna_experiment", "research_diagnostic_plugins"]
