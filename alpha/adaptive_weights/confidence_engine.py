from __future__ import annotations

from decimal import Decimal

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    ConfidenceAssessment,
    ContributionConfidence,
    ContributionEstimate,
    EvidencePartition,
    StabilityAssessment,
    StabilityClass,
)


class ContributionConfidenceEngine:
    def __init__(
        self,
        *,
        minimum_total_samples: int = 20,
        minimum_holdout_samples: int = 10,
        minimum_forward_samples: int = 10,
    ) -> None:
        self.minimum_total_samples = minimum_total_samples
        self.minimum_holdout_samples = minimum_holdout_samples
        self.minimum_forward_samples = minimum_forward_samples

    def assess(
        self,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        contributions: tuple[ContributionEstimate, ...],
        stabilities: tuple[StabilityAssessment, ...],
    ) -> tuple[ConfidenceAssessment, ...]:
        stability_by_component = {item.component: item for item in stabilities}
        contribution_by_component = {item.component: item for item in contributions}
        assessments = []
        for component in AlphaComponent:
            available = tuple(
                item for item in evidence if item.score_for(component) is not None
            )
            holdout = sum(
                item.partition is EvidencePartition.HOLDOUT for item in available
            )
            forward = sum(
                item.partition is EvidencePartition.FORWARD_OBSERVED
                for item in available
            )
            confidence, penalty, reasons = self._classify(
                contribution_by_component[component],
                stability_by_component[component],
                len(available),
                holdout,
                forward,
            )
            assessments.append(
                ConfidenceAssessment(
                    component=component,
                    confidence=confidence,
                    sample_size=len(available),
                    holdout_sample_size=holdout,
                    forward_sample_size=forward,
                    uncertainty_penalty=penalty,
                    reasons=reasons,
                )
            )
        return tuple(assessments)

    def _classify(
        self,
        contribution: ContributionEstimate,
        stability: StabilityAssessment,
        total: int,
        holdout: int,
        forward: int,
    ) -> tuple[ContributionConfidence, Decimal, tuple[str, ...]]:
        reasons = []
        if total < self.minimum_total_samples:
            reasons.append(f"total sample {total} below {self.minimum_total_samples}")
        if holdout < self.minimum_holdout_samples:
            reasons.append(
                f"holdout sample {holdout} below {self.minimum_holdout_samples}"
            )
        if forward < self.minimum_forward_samples:
            reasons.append(
                f"forward sample {forward} below {self.minimum_forward_samples}"
            )
        if contribution.marginal_contribution is None:
            reasons.append("unique marginal contribution unavailable")
        if (
            total < self.minimum_total_samples
            or contribution.marginal_contribution is None
        ):
            return ContributionConfidence.INSUFFICIENT, Decimal("0.90"), tuple(reasons)
        if holdout < self.minimum_holdout_samples:
            return ContributionConfidence.WEAK, Decimal("0.75"), tuple(reasons)
        if stability.classification in {
            StabilityClass.UNSTABLE,
            StabilityClass.INSUFFICIENT_EVIDENCE,
        }:
            reasons.append(f"stability is {stability.classification.value}")
            return ContributionConfidence.WEAK, Decimal("0.65"), tuple(reasons)
        if (
            forward >= self.minimum_forward_samples
            and stability.classification is StabilityClass.ROBUST
        ):
            return ContributionConfidence.STRONG, Decimal("0.10"), tuple(reasons)
        return ContributionConfidence.MODERATE, Decimal("0.35"), tuple(reasons)


__all__ = ["ContributionConfidenceEngine"]
