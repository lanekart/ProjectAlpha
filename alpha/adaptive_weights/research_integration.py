from __future__ import annotations

from decimal import Decimal

from alpha.adaptive_weights.models import (
    ADAPTIVE_WEIGHT_SCHEMA_VERSION,
    CandidateWeightPolicy,
    ContributionEstimate,
    OverlapFinding,
    RedundancyClass,
    StabilityAssessment,
    StabilityClass,
)
from alpha.adaptive_weights.policy_registry import CandidateWeightPolicyRegistry
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


def record_adaptive_weight_experiment(
    policy: CandidateWeightPolicy,
    contributions: tuple[ContributionEstimate, ...],
    overlaps: tuple[OverlapFinding, ...],
    stabilities: tuple[StabilityAssessment, ...],
    *,
    registry: ResearchExperimentRegistry | None = None,
) -> bool:
    provenance = _provenance(policy)
    strongest_positive = max(
        (
            item
            for item in contributions
            if item.marginal_contribution is not None
            and item.marginal_contribution > Decimal("0")
        ),
        key=lambda item: item.marginal_contribution or Decimal("0"),
        default=None,
    )
    strongest_negative = min(
        (
            item
            for item in contributions
            if item.marginal_contribution is not None
            and item.marginal_contribution < Decimal("0")
        ),
        key=lambda item: item.marginal_contribution or Decimal("0"),
        default=None,
    )
    redundant = max(
        (
            item
            for item in overlaps
            if item.redundancy_class
            in {
                RedundancyClass.PARTIALLY_REDUNDANT,
                RedundancyClass.HIGHLY_REDUNDANT,
                RedundancyClass.SAME_SOURCE,
            }
        ),
        key=lambda item: abs(item.score_correlation or Decimal("0")),
        default=None,
    )
    stable = max(
        (
            item
            for item in stabilities
            if item.classification
            in {StabilityClass.ROBUST, StabilityClass.MODERATELY_STABLE}
        ),
        key=lambda item: item.directional_stability or Decimal("0"),
        default=None,
    )
    conditional = max(
        (
            item
            for item in stabilities
            if item.classification is StabilityClass.CONDITIONAL
        ),
        key=lambda item: item.sample_size,
        default=None,
    )
    next_ablation = min(contributions, key=lambda item: item.sample_size)
    blockers = sorted(
        {
            blocker
            for decision in policy.component_decisions
            for blocker in decision.blocking_reasons
        }
    )
    treatment = (
        _metric(
            "adaptive_weights.strongest_positive_component",
            "Strongest positive component",
            strongest_positive.component.value if strongest_positive else None,
            "component",
            provenance,
        ),
        _metric(
            "adaptive_weights.strongest_negative_component",
            "Strongest negative component",
            strongest_negative.component.value if strongest_negative else None,
            "component",
            provenance,
        ),
        _metric(
            "adaptive_weights.most_redundant_pair",
            "Most redundant component pair",
            (
                f"{redundant.component_a.value}<->{redundant.component_b.value}"
                if redundant
                else None
            ),
            "component_pair",
            provenance,
        ),
        _metric(
            "adaptive_weights.most_stable_component",
            "Most stable component",
            stable.component.value if stable else None,
            "component",
            provenance,
        ),
        _metric(
            "adaptive_weights.most_conditional_component",
            "Most conditional component",
            conditional.component.value if conditional else None,
            "component",
            provenance,
        ),
        _metric(
            "adaptive_weights.highest_value_next_ablation",
            "Highest-value next ablation",
            next_ablation.component.value,
            "component",
            provenance,
        ),
        _metric(
            "adaptive_weights.current_candidate_policy",
            "Current candidate weight policy",
            policy.policy_id,
            "policy_id",
            provenance,
        ),
        _metric(
            "adaptive_weights.promotion_blockers",
            "Promotion blockers",
            "; ".join(blockers) if blockers else "none recorded",
            "text",
            provenance,
        ),
        _metric(
            "adaptive_weights.completed_outcomes",
            "Completed outcomes",
            policy.outcome_count,
            "count",
            provenance,
        ),
    )
    baseline = tuple(
        _metric(
            f"adaptive_weights.canonical.{item.component.value}",
            f"Canonical {_label(item.component.value)} weight",
            item.weight,
            "weight_points",
            provenance,
        )
        for item in policy.canonical_weights.weights
    )
    experiment = RegisteredResearchExperiment(
        experiment_id=policy.policy_id,
        title="Adaptive indicator weight contribution research",
        subsystem=ResearchSubsystem.ADAPTIVE_WEIGHTS,
        experiment_date=policy.created_at.date(),
        purpose=(
            "Estimate stable unique payoff contribution and freeze a governed "
            "research-only candidate weight policy."
        ),
        evidence_sources=(
            "performance_intelligence recommendation ledger",
            "forward validation",
            "TradingView Research Laboratory matched ablations",
        ),
        baseline=baseline,
        treatment=treatment,
        metrics=(
            "realised R contribution",
            "matched ablation expectancy",
            "overlap",
            "stability",
            "holdout consistency",
        ),
        statistical_confidence=ResearchConfidence.LOW,
        decision=ExperimentDecision.INCONCLUSIVE,
        status=ExperimentStatus.COMPLETED,
        findings=(
            f"candidate={policy.policy_id}",
            f"quality={policy.quality_state.value}",
            f"holdout={policy.holdout_status}",
            f"forward={policy.forward_status}",
        ),
        lessons_learned=tuple(blockers)
        or ("No automatic production mutation permitted.",),
    )
    return (registry or ResearchExperimentRegistry()).record(experiment)


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id="adaptive-indicator-weight-research",
            title="Adaptive indicator payoff contribution research",
            subsystem=ResearchSubsystem.ADAPTIVE_WEIGHTS,
            source_module="alpha.adaptive_weights.policy_registry",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    policies = CandidateWeightPolicyRegistry().load()
    experiments = tuple(
        item
        for item in ResearchExperimentRegistry().load()
        if item.subsystem is ResearchSubsystem.ADAPTIVE_WEIGHTS
    )
    if not policies:
        return DiagnosticEvidence(
            diagnostic_id="adaptive-indicator-weight-research",
            title="Adaptive indicator payoff contribution research",
            subsystem=ResearchSubsystem.ADAPTIVE_WEIGHTS,
            source_module="alpha.adaptive_weights.policy_registry",
            source_version=ADAPTIVE_WEIGHT_SCHEMA_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No immutable adaptive-weight candidate policy is registered.",
            recommended_action=(
                "Run alpha adaptive-weights propose on completed outcomes."
            ),
        )
    policy = policies[-1]
    latest = experiments[-1] if experiments else None
    metrics = (
        latest.treatment
        if latest is not None
        else (
            _metric(
                "adaptive_weights.current_candidate_policy",
                "Current candidate weight policy",
                policy.policy_id,
                "policy_id",
                _provenance(policy),
            ),
            _metric(
                "adaptive_weights.completed_outcomes",
                "Completed outcomes",
                policy.outcome_count,
                "count",
                _provenance(policy),
            ),
        )
    )
    return DiagnosticEvidence(
        diagnostic_id="adaptive-indicator-weight-research",
        title="Adaptive indicator payoff contribution research",
        subsystem=ResearchSubsystem.ADAPTIVE_WEIGHTS,
        source_module="alpha.adaptive_weights.policy_registry",
        source_version=ADAPTIVE_WEIGHT_SCHEMA_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.NASCENT,
        evidence_quality=EvidenceQuality.LOW,
        confidence=ResearchConfidence.LOW,
        bottleneck_status=BottleneckStatus.PROVEN,
        metrics=metrics,
        finding=(
            f"Latest candidate {policy.policy_id} remains {policy.state.value}; "
            f"holdout={policy.holdout_status}, forward={policy.forward_status}."
        ),
        recommended_action=(
            "Complete holdout and forward validation before policy review."
        ),
        dependencies=("completed realised outcomes", "matched component ablations"),
        limitations=(
            "Candidate weights are research-only.",
            "No automatic deployment or production mutation is permitted.",
        ),
    )


def _metric(
    metric_id: str,
    label: str,
    value: bool | int | str | Decimal | None,
    unit: str,
    provenance: MetricProvenance,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        availability=(
            MetricAvailability.UNAVAILABLE
            if value is None
            else MetricAvailability.AVAILABLE
        ),
        provenance=provenance,
    )


def _provenance(policy: CandidateWeightPolicy) -> MetricProvenance:
    return MetricProvenance(
        source="adaptive weight immutable policy and research registry",
        definition="Completed-outcome payoff contribution with holdout separation",
        population=f"{policy.evidence_window}; n={policy.outcome_count}",
        version=f"{policy.dataset_version}|{policy.method_version}",
    )


def _label(value: str) -> str:
    return value.replace("_", " ").title()


__all__ = ["record_adaptive_weight_experiment", "research_diagnostic_plugins"]
