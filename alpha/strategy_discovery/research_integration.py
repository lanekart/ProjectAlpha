from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256

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
from alpha.strategy_discovery.models import StrategyDiscoveryReport
from alpha.strategy_discovery.strategy_registry import StrategyRegistry


def record_discovery_experiment(
    report: StrategyDiscoveryReport,
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    experiment_id = (
        "strategy-discovery-"
        + sha256(
            (
                report.dataset.dataset_version
                + "|"
                + report.search_manifest.search_space_hash
            ).encode()
        ).hexdigest()[:20]
    )
    top = report.leaderboard[0] if report.leaderboard else None
    baseline = next(
        (
            item
            for item in report.benchmark_entries
            if item.strategy.family.value == "APPROVAL_POLICY_V1"
        ),
        None,
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=experiment_id,
        title="Walk-forward strategy discovery and generalisation",
        subsystem=ResearchSubsystem.STRATEGY_DISCOVERY,
        experiment_date=report.generated_at.date(),
        purpose=(
            "Test whether bounded interpretable strategies retain positive "
            "expectancy on chronological unseen evidence."
        ),
        evidence_sources=(
            report.dataset.source,
            "alpha.strategy_discovery.strategy_registry",
        ),
        baseline=(
            _metric(
                "incumbent_validation_expectancy_pct",
                "APPROVAL_POLICY_V1 validation expectancy",
                None
                if baseline is None
                else baseline.evaluation.validation_metrics.expectancy_pct,
                report,
            ),
        ),
        treatment=(
            _metric(
                "top_candidate_validation_expectancy_pct",
                "Top candidate validation expectancy",
                None
                if top is None
                else top.evaluation.validation_metrics.expectancy_pct,
                report,
            ),
        ),
        metrics=(
            "expectancy after costs",
            "chronological fold consistency",
            "holdout expectancy",
            "robustness",
            "multiple-testing adjustment",
        ),
        statistical_confidence=(
            ResearchConfidence.LOW
            if report.dataset.population_class.value != "AUTHORITATIVE"
            else ResearchConfidence.MEDIUM
        ),
        decision=(
            ExperimentDecision.ACCEPT
            if report.decision.startswith("PUBLISH_")
            else ExperimentDecision.REJECT
        ),
        status=ExperimentStatus.COMPLETED,
        findings=(
            report.decision,
            f"Strategies tested: {report.search_manifest.total_variants}",
            f"Historical truth: {report.dataset.population_class.value}",
        ),
        lessons_learned=(
            *report.dominant_failure_reasons,
            report.highest_value_evidence_gap,
        ),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="strategy-discovery-generalisation",
            title="Walk-forward strategy generalisation",
            subsystem=ResearchSubsystem.STRATEGY_DISCOVERY,
            source_module="alpha.strategy_discovery.strategy_registry",
            collector=_collect_strategy_discovery_evidence,
        ),
    )


def _collect_strategy_discovery_evidence() -> DiagnosticEvidence:
    board = StrategyRegistry().latest_leaderboard_payload()
    if board is None:
        return DiagnosticEvidence(
            diagnostic_id="strategy-discovery-generalisation",
            title="Walk-forward strategy generalisation",
            subsystem=ResearchSubsystem.STRATEGY_DISCOVERY,
            source_module="alpha.strategy_discovery.strategy_registry",
            source_version="strategy-discovery-v1",
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed strategy-discovery leaderboard is registered.",
            recommended_action="Run alpha strategy discovery-report.",
        )
    entries = board.get("entries", [])
    count = len(entries) if isinstance(entries, list) else 0
    decision = str(board.get("decision", "UNKNOWN"))
    return DiagnosticEvidence(
        diagnostic_id="strategy-discovery-generalisation",
        title="Walk-forward strategy generalisation",
        subsystem=ResearchSubsystem.STRATEGY_DISCOVERY,
        source_module="alpha.strategy_discovery.strategy_registry",
        source_version="strategy-discovery-v1",
        state=DiagnosticState.AVAILABLE,
        maturity=(
            ResearchMaturity.PARTIAL
            if decision.startswith("PUBLISH_")
            else ResearchMaturity.BLOCKED
        ),
        evidence_quality=EvidenceQuality.MEDIUM,
        confidence=ResearchConfidence.LOW,
        bottleneck_status=BottleneckStatus.PROVEN,
        metrics=(
            ResearchMetric(
                metric_id="strategy_variants_evaluated",
                label="Strategy variants evaluated",
                value=count,
                unit="count",
                provenance=MetricProvenance(
                    source="strategy discovery registry",
                    definition="Immutable leaderboard entries in the latest run",
                    population=str(board.get("dataset_version", "unknown")),
                    version="strategy-discovery-v1",
                ),
            ),
        ),
        finding=f"Latest deterministic strategy decision: {decision}.",
        recommended_action=(
            "Close the highest-value evidence gap before any shadow publication."
        ),
        dependencies=(
            "authoritative point-in-time identity and corporate-action evidence",
        ),
        limitations=("Historical discovery evidence is not measured forward ROI.",),
    )


def _metric(
    metric_id: str,
    label: str,
    value: Decimal | None,
    report: StrategyDiscoveryReport,
) -> ResearchMetric:
    normalized: Decimal | None
    try:
        normalized = None if value is None else Decimal(value)
    except InvalidOperation:
        normalized = None
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=normalized,
        unit="percent",
        availability=(
            MetricAvailability.UNAVAILABLE
            if normalized is None
            else MetricAvailability.AVAILABLE
        ),
        provenance=MetricProvenance(
            source="strategy discovery evaluator",
            definition="Average realised return after configured costs",
            population=report.dataset.dataset_version,
            version="strategy-evaluator-v1",
        ),
    )


__all__ = ["record_discovery_experiment", "research_diagnostic_plugins"]
