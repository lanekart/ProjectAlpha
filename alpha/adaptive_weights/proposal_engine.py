from __future__ import annotations

from decimal import Decimal

from alpha.adaptive_weights.models import (
    AblationContribution,
    AlphaComponent,
    ComponentDecisionState,
    ComponentWeight,
    ComponentWeightDecision,
    ConfidenceAssessment,
    ContributionConfidence,
    ContributionEstimate,
    OverlapFinding,
    ProposalGuardrails,
    RedundancyClass,
    StabilityAssessment,
    StabilityClass,
    WeightLayer,
    WeightProposal,
    WeightSet,
    canonical_weight_set,
)

_ONE = Decimal("1")


class AdaptiveWeightProposalEngine:
    def __init__(self, guardrails: ProposalGuardrails | None = None) -> None:
        self.guardrails = guardrails or ProposalGuardrails()

    def propose(
        self,
        contributions: tuple[ContributionEstimate, ...],
        stabilities: tuple[StabilityAssessment, ...],
        confidences: tuple[ConfidenceAssessment, ...],
        overlaps: tuple[OverlapFinding, ...],
        *,
        ablations: tuple[AblationContribution, ...] = (),
        evidence_count: int,
        policy_id: str = "ALPHA_WEIGHT_RESEARCH_DRAFT",
    ) -> WeightProposal:
        baseline = canonical_weight_set()
        contribution_by_component = {item.component: item for item in contributions}
        stability_by_component = {item.component: item for item in stabilities}
        confidence_by_component = {item.component: item for item in confidences}
        ablation_by_component = {item.component: item for item in ablations}
        raw_values: dict[AlphaComponent, Decimal] = {}
        metadata: dict[
            AlphaComponent,
            tuple[
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                tuple[str, ...],
                tuple[str, ...],
            ],
        ] = {}
        for component in AlphaComponent:
            current = baseline.for_component(component)
            contribution = contribution_by_component[component]
            stability = stability_by_component[component]
            confidence = confidence_by_component[component]
            ablation = ablation_by_component.get(component)
            payoff_signal = _payoff_signal(contribution, ablation)
            payoff_multiplier = _ONE + Decimal("0.20") * payoff_signal
            confidence_multiplier = _confidence_multiplier(confidence.confidence)
            stability_multiplier = _stability_multiplier(stability.classification)
            uniqueness_multiplier, overlap_reasons = _uniqueness_multiplier(
                component, overlaps, self.guardrails.overlap_penalty
            )
            proposed_raw = (
                current
                * payoff_multiplier
                * confidence_multiplier
                * stability_multiplier
                * uniqueness_multiplier
            )
            shrinkage = _shrinkage(confidence.confidence, self.guardrails)
            shrunk = current + (proposed_raw - current) * (_ONE - shrinkage)
            blockers = list(overlap_reasons)
            holdout = contribution.partition_contributions.get("HOLDOUT")
            if holdout is not None and holdout < Decimal("0") and shrunk > current:
                shrunk = current
                blockers.append("negative holdout contribution blocks increase")
            if (
                confidence.holdout_sample_size < self.guardrails.minimum_holdout_samples
                and shrunk > current
            ):
                shrunk = current
                blockers.append("insufficient holdout evidence blocks increase")
            relative_floor = current * (_ONE - self.guardrails.maximum_relative_change)
            relative_cap = current * (_ONE + self.guardrails.maximum_relative_change)
            bounded = min(
                self.guardrails.maximum_absolute_weight,
                relative_cap,
                max(self.guardrails.minimum_absolute_weight, relative_floor, shrunk),
            )
            raw_values[component] = bounded
            supporting = (
                f"marginal={_text(contribution.marginal_contribution)}",
                f"standalone={_text(contribution.standalone_contribution)}",
                f"holdout={_text(holdout)}",
                f"stability={stability.classification.value}",
                f"confidence={confidence.confidence.value}",
            )
            metadata[component] = (
                proposed_raw,
                payoff_multiplier,
                confidence_multiplier,
                stability_multiplier,
                uniqueness_multiplier,
                supporting,
                tuple(blockers),
            )
        normalized = _bounded_normalize(raw_values, baseline, self.guardrails)
        decisions = tuple(
            self._decision(
                component,
                normalized[component],
                baseline,
                contribution_by_component[component],
                stability_by_component[component],
                confidence_by_component[component],
                metadata[component],
            )
            for component in AlphaComponent
        )
        proposed = WeightSet(
            layer=WeightLayer.RESEARCH_PROPOSED_WEIGHTS,
            policy_id=policy_id,
            weights=tuple(
                ComponentWeight(component, normalized[component])
                for component in AlphaComponent
            ),
        )
        return WeightProposal(
            baseline=baseline,
            proposed=proposed,
            decisions=decisions,
            guardrails=self.guardrails,
            evidence_count=evidence_count,
            validation_status=_partition_status(contributions, "VALIDATION"),
            holdout_status=_partition_status(contributions, "HOLDOUT"),
            forward_status=_partition_status(contributions, "FORWARD_OBSERVED"),
        )

    def _decision(
        self,
        component: AlphaComponent,
        proposed: Decimal,
        baseline: WeightSet,
        contribution: ContributionEstimate,
        stability: StabilityAssessment,
        confidence: ConfidenceAssessment,
        metadata: tuple[
            Decimal,
            Decimal,
            Decimal,
            Decimal,
            Decimal,
            tuple[str, ...],
            tuple[str, ...],
        ],
    ) -> ComponentWeightDecision:
        (
            proposed_raw,
            payoff_multiplier,
            confidence_multiplier,
            stability_multiplier,
            uniqueness_multiplier,
            supporting,
            blockers,
        ) = metadata
        current = baseline.for_component(component)
        change = proposed - current
        if confidence.confidence is ContributionConfidence.INSUFFICIENT:
            state = ComponentDecisionState.INSUFFICIENT_EVIDENCE
            reason = "completed evidence is insufficient; canonical weight retained"
        elif stability.classification is StabilityClass.CONDITIONAL:
            state = ComponentDecisionState.CONDITIONAL_WEIGHT
            reason = "payoff contribution is conditional on setup or regime"
        elif change > Decimal("0.01"):
            state = ComponentDecisionState.INCREASE_WEIGHT
            reason = "stable unique payoff contribution supports a bounded increase"
        elif change < Decimal("-0.01"):
            state = ComponentDecisionState.DECREASE_WEIGHT
            reason = (
                "negative or redundant payoff contribution supports a bounded decrease"
            )
        else:
            state = ComponentDecisionState.MAINTAIN_WEIGHT
            reason = "evidence does not justify a material revision"
        return ComponentWeightDecision(
            component=component,
            current_weight=current,
            proposed_raw_weight=proposed_raw,
            proposed_weight=proposed,
            absolute_change=change,
            relative_change=change / current if current else Decimal("0"),
            payoff_multiplier=payoff_multiplier,
            confidence_multiplier=confidence_multiplier,
            stability_multiplier=stability_multiplier,
            uniqueness_multiplier=uniqueness_multiplier,
            decision=state,
            primary_reason=reason,
            supporting_metrics=supporting,
            blocking_reasons=blockers,
        )


def _payoff_signal(
    contribution: ContributionEstimate,
    ablation: AblationContribution | None,
) -> Decimal:
    values = [
        value
        for value in (
            contribution.marginal_contribution,
            contribution.leave_one_out_contribution,
            ablation.delta_expectancy if ablation is not None else None,
        )
        if value is not None
    ]
    if not values:
        return Decimal("0")
    mean = sum(values, start=Decimal("0")) / Decimal(len(values))
    return max(Decimal("-1"), min(Decimal("1"), mean))


def _confidence_multiplier(confidence: ContributionConfidence) -> Decimal:
    return {
        ContributionConfidence.STRONG: Decimal("1"),
        ContributionConfidence.MODERATE: Decimal("0.98"),
        ContributionConfidence.WEAK: Decimal("0.95"),
        ContributionConfidence.INSUFFICIENT: Decimal("1"),
    }[confidence]


def _stability_multiplier(stability: StabilityClass) -> Decimal:
    return {
        StabilityClass.ROBUST: Decimal("1"),
        StabilityClass.MODERATELY_STABLE: Decimal("0.98"),
        StabilityClass.CONDITIONAL: Decimal("0.98"),
        StabilityClass.UNSTABLE: Decimal("0.90"),
        StabilityClass.NEGATIVE: Decimal("0.80"),
        StabilityClass.INSUFFICIENT_EVIDENCE: Decimal("1"),
    }[stability]


def _uniqueness_multiplier(
    component: AlphaComponent,
    overlaps: tuple[OverlapFinding, ...],
    configured_penalty: Decimal,
) -> tuple[Decimal, tuple[str, ...]]:
    relevant = tuple(
        item
        for item in overlaps
        if item.component_a is component or item.component_b is component
    )
    classes = {item.redundancy_class for item in relevant}
    if RedundancyClass.SAME_SOURCE in classes:
        return configured_penalty, ("same-source evidence receives overlap penalty",)
    if RedundancyClass.HIGHLY_REDUNDANT in classes:
        return Decimal("0.80"), ("high indicator overlap caps weight increase",)
    if RedundancyClass.PARTIALLY_REDUNDANT in classes:
        return Decimal("0.90"), ("partial overlap receives shrinkage",)
    return Decimal("1"), ()


def _shrinkage(
    confidence: ContributionConfidence, guardrails: ProposalGuardrails
) -> Decimal:
    return {
        ContributionConfidence.STRONG: guardrails.strong_evidence_shrinkage,
        ContributionConfidence.MODERATE: guardrails.moderate_evidence_shrinkage,
        ContributionConfidence.WEAK: guardrails.weak_evidence_shrinkage,
        ContributionConfidence.INSUFFICIENT: Decimal("1"),
    }[confidence]


def _bounded_normalize(
    values: dict[AlphaComponent, Decimal],
    baseline: WeightSet,
    guardrails: ProposalGuardrails,
) -> dict[AlphaComponent, Decimal]:
    lower = {
        component: max(
            guardrails.minimum_absolute_weight,
            baseline.for_component(component)
            * (_ONE - guardrails.maximum_relative_change),
        )
        for component in AlphaComponent
    }
    upper = {
        component: min(
            guardrails.maximum_absolute_weight,
            baseline.for_component(component)
            * (_ONE + guardrails.maximum_relative_change),
        )
        for component in AlphaComponent
    }
    normalized = {
        component: min(upper[component], max(lower[component], values[component]))
        for component in AlphaComponent
    }
    for _ in range(40):
        difference = Decimal("100") - sum(normalized.values(), start=Decimal("0"))
        if abs(difference) <= Decimal("0.0000001"):
            break
        if difference > 0:
            eligible = [
                component
                for component in AlphaComponent
                if normalized[component] < upper[component]
            ]
            capacity = sum(
                (upper[item] - normalized[item] for item in eligible),
                start=Decimal("0"),
            )
            for component in eligible:
                share = (
                    difference * (upper[component] - normalized[component]) / capacity
                    if capacity
                    else Decimal("0")
                )
                normalized[component] = min(
                    upper[component], normalized[component] + share
                )
        else:
            eligible = [
                component
                for component in AlphaComponent
                if normalized[component] > lower[component]
            ]
            capacity = sum(
                (normalized[item] - lower[item] for item in eligible),
                start=Decimal("0"),
            )
            for component in eligible:
                share = (
                    (-difference)
                    * (normalized[component] - lower[component])
                    / capacity
                    if capacity
                    else Decimal("0")
                )
                normalized[component] = max(
                    lower[component], normalized[component] - share
                )
    total = sum(normalized.values(), start=Decimal("0"))
    residual = Decimal("100") - total
    if residual:
        for component in AlphaComponent:
            candidate = normalized[component] + residual
            if lower[component] <= candidate <= upper[component]:
                normalized[component] = candidate
                break
    return normalized


def _partition_status(
    contributions: tuple[ContributionEstimate, ...], partition: str
) -> str:
    available = [
        item.partition_contributions.get(partition)
        for item in contributions
        if item.partition_contributions.get(partition) is not None
    ]
    return "AVAILABLE" if available else "INSUFFICIENT_EVIDENCE"


def _text(value: Decimal | None) -> str:
    return (
        str(value.quantize(Decimal("0.0001"))) if value is not None else "unavailable"
    )


__all__ = ["AdaptiveWeightProposalEngine"]
