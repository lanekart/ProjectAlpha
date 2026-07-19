from __future__ import annotations

from collections import defaultdict

from alpha.adaptive_weights.confidence_engine import ContributionConfidenceEngine
from alpha.adaptive_weights.marginal_contribution import MarginalContributionEngine
from alpha.adaptive_weights.models import (
    CompletedOutcomeEvidence,
    ConditionalWeightPolicy,
    ConditionalWeightSet,
    EvidenceQuality,
    ProposalGuardrails,
    WeightSet,
)
from alpha.adaptive_weights.overlap_analysis import IndicatorOverlapEngine
from alpha.adaptive_weights.proposal_engine import AdaptiveWeightProposalEngine
from alpha.adaptive_weights.stability_analysis import ContributionStabilityEngine


class ConditionalWeightResearchEngine:
    def __init__(
        self,
        *,
        minimum_sample_size: int = 20,
        guardrails: ProposalGuardrails | None = None,
    ) -> None:
        self.minimum_sample_size = minimum_sample_size
        self.guardrails = guardrails or ProposalGuardrails()

    def build(
        self,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        *,
        universal: WeightSet | None,
    ) -> ConditionalWeightPolicy:
        groups = _conditional_groups(evidence)
        conditionals = []
        for key, records in sorted(groups.items(), key=lambda item: str(item[0])):
            if len(records) < self.minimum_sample_size:
                continue
            contributions = MarginalContributionEngine().analyze(tuple(records))
            stabilities = ContributionStabilityEngine(
                minimum_sample_size=self.minimum_sample_size
            ).analyze(tuple(records), contributions)
            confidence = ContributionConfidenceEngine(
                minimum_total_samples=self.minimum_sample_size,
                minimum_holdout_samples=max(2, self.minimum_sample_size // 5),
                minimum_forward_samples=max(2, self.minimum_sample_size // 5),
            ).assess(tuple(records), contributions, stabilities)
            overlaps = IndicatorOverlapEngine(
                minimum_sample_size=self.minimum_sample_size
            ).analyze(tuple(records))
            setup, regime, horizon = key
            policy_id = "CONDITIONAL_" + "_".join(
                item or "ANY" for item in (setup, regime, horizon)
            )
            proposal = AdaptiveWeightProposalEngine(self.guardrails).propose(
                contributions,
                stabilities,
                confidence,
                overlaps,
                evidence_count=len(records),
                policy_id=policy_id,
            )
            conditionals.append(
                ConditionalWeightSet(
                    setup=setup,
                    regime=regime,
                    horizon=horizon,
                    sample_size=len(records),
                    weights=proposal.proposed,
                    evidence_quality=EvidenceQuality.SUFFICIENT,
                )
            )
        return ConditionalWeightPolicy(
            universal=universal,
            conditionals=tuple(conditionals),
            minimum_sample_size=self.minimum_sample_size,
        )


def _conditional_groups(
    evidence: tuple[CompletedOutcomeEvidence, ...],
) -> dict[tuple[str | None, str | None, str | None], list[CompletedOutcomeEvidence]]:
    groups: dict[
        tuple[str | None, str | None, str | None], list[CompletedOutcomeEvidence]
    ] = defaultdict(list)
    for item in evidence:
        if item.setup_family != "UNKNOWN" and item.market_regime != "UNKNOWN":
            groups[(item.setup_family, item.market_regime, None)].append(item)
        if item.setup_family != "UNKNOWN":
            groups[(item.setup_family, None, None)].append(item)
        if item.market_regime != "UNKNOWN":
            groups[(None, item.market_regime, None)].append(item)
        if item.holding_horizon != "UNKNOWN":
            groups[(None, None, item.holding_horizon)].append(item)
    return groups


__all__ = ["ConditionalWeightResearchEngine"]
