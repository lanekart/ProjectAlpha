from __future__ import annotations

from decimal import Decimal

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
from alpha.strategy_lab.experiment_registry import StrategyLabExperimentRegistry
from alpha.strategy_lab.models import STRATEGY_LAB_SCHEMA_VERSION, StrategyLabReport


def record_lab_experiment(
    report: StrategyLabReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    strongest = next(
        (
            item
            for item in report.results
            if item.strategy.strategy_id == report.strongest_strategy_id
        ),
        None,
    )
    metric = _metric(
        metric_id="strategy_lab.top_net_expectancy_pct",
        label="Top reconstructed net expectancy",
        value=None if strongest is None else strongest.metrics.expectancy_pct,
        report=report,
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=report.experiment_id,
        title="Strategy and indicator combination backtest lab",
        subsystem=ResearchSubsystem.STRATEGY_LAB,
        experiment_date=report.generated_at.date(),
        purpose=(
            "Compare bounded interpretable strategy and indicator combinations under "
            "consistent point-in-time evidence and execution assumptions."
        ),
        evidence_sources=(
            "candidate_learning_ledger",
            "alpha.strategy_discovery",
            "alpha.strategy_lab.experiment_registry",
        ),
        baseline=(),
        treatment=(metric,),
        metrics=(
            "precision",
            "expectancy after costs",
            "profit factor",
            "payoff ratio",
            "drawdown",
            "stability",
            "component attribution",
            "multiple-testing adjustment",
        ),
        statistical_confidence=ResearchConfidence.LOW,
        decision=(
            ExperimentDecision.ACCEPT
            if report.final_conclusion.startswith("RECOMMEND_")
            else ExperimentDecision.INCONCLUSIVE
        ),
        status=ExperimentStatus.COMPLETED,
        findings=(
            report.final_conclusion,
            f"Strategies tested: {report.search_space.total_trials}",
            f"Evidence class: {report.evidence_class.value}",
        ),
        lessons_learned=(report.highest_value_evidence_gap,),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="strategy-indicator-backtest-lab",
            title="Strategy and indicator combination evidence",
            subsystem=ResearchSubsystem.STRATEGY_LAB,
            source_module="alpha.strategy_lab.experiment_registry",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    payload = StrategyLabExperimentRegistry().latest_payload()
    if payload is None:
        return DiagnosticEvidence(
            diagnostic_id="strategy-indicator-backtest-lab",
            title="Strategy and indicator combination evidence",
            subsystem=ResearchSubsystem.STRATEGY_LAB,
            source_module="alpha.strategy_lab.experiment_registry",
            source_version=STRATEGY_LAB_SCHEMA_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No strategy-lab experiment is registered.",
            recommended_action="Run alpha strategy-lab report.",
        )
    results = payload.get("results", [])
    result_rows = results if isinstance(results, list) else []
    search = payload.get("search_space", {})
    search_payload = search if isinstance(search, dict) else {}
    attributions = payload.get("component_attribution", [])
    attribution_rows = attributions if isinstance(attributions, list) else []
    classifications = {
        str(item.get("classification", "UNKNOWN"))
        for item in result_rows
        if isinstance(item, dict)
    }
    provenance = MetricProvenance(
        source="strategy lab immutable experiment registry",
        definition="Latest bounded strategy-lab experiment",
        population=str(payload.get("dataset_version", "unknown")),
        version=STRATEGY_LAB_SCHEMA_VERSION,
    )
    return DiagnosticEvidence(
        diagnostic_id="strategy-indicator-backtest-lab",
        title="Strategy and indicator combination evidence",
        subsystem=ResearchSubsystem.STRATEGY_LAB,
        source_module="alpha.strategy_lab.experiment_registry",
        source_version=STRATEGY_LAB_SCHEMA_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.BLOCKED,
        evidence_quality=EvidenceQuality.LOW,
        confidence=ResearchConfidence.LOW,
        bottleneck_status=BottleneckStatus.PROVEN,
        metrics=(
            ResearchMetric(
                metric_id="strategy_lab.strategies_tested",
                label="Strategy variants tested",
                value=int(search_payload.get("total_trials", len(result_rows))),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="strategy_lab.component_attributions",
                label="Component attribution comparisons",
                value=len(attribution_rows),
                unit="count",
                provenance=provenance,
            ),
            ResearchMetric(
                metric_id="strategy_lab.final_conclusion",
                label="Strategy lab final conclusion",
                value=str(payload.get("final_conclusion", "UNKNOWN")),
                unit="classification",
                provenance=provenance,
            ),
        ),
        finding=(
            f"Latest lab classifications: {', '.join(sorted(classifications))}; "
            f"conclusion={payload.get('final_conclusion', 'UNKNOWN')}."
        ),
        recommended_action=str(
            payload.get(
                "highest_value_evidence_gap",
                "Acquire authoritative completed outcomes.",
            )
        ),
        dependencies=(
            "authoritative point-in-time outcomes",
            "corporate-action-complete price history",
        ),
        limitations=(
            "Reconstructed historical comparisons are not measured forward ROI.",
            "Production influence is disabled.",
        ),
    )


def _metric(
    *,
    metric_id: str,
    label: str,
    value: Decimal | None,
    report: StrategyLabReport,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit="percent",
        availability=(
            MetricAvailability.UNAVAILABLE
            if value is None
            else MetricAvailability.AVAILABLE
        ),
        provenance=MetricProvenance(
            source="strategy lab performance metrics",
            definition="Average reconstructed realised return after configured costs",
            population=report.dataset_version,
            version="strategy-lab-metrics-v1",
        ),
    )


__all__ = ["record_lab_experiment", "research_diagnostic_plugins"]
