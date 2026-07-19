from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from alpha.adaptive_weights.models import (
    CompletedOutcomeEvidence,
    ComponentDecisionState,
    ComponentWeightDecision,
    EvidencePartition,
    OverlapFinding,
    PolicyComparison,
    PromotionAssessment,
    PromotionDecision,
    RedundancyClass,
    ResearchPerformance,
    StabilityAssessment,
    StabilityClass,
)


@dataclass(frozen=True, slots=True)
class PromotionGuardrails:
    minimum_trades_per_partition: int = 30
    minimum_symbols: int = 3
    minimum_sectors: int = 2
    maximum_drawdown_worsening: Decimal = Decimal("0.05")
    maximum_cost_worsening: Decimal = Decimal("0.05")
    maximum_concentration_worsening: Decimal = Decimal("0.10")


class CandidateWeightPromotionEngine:
    def __init__(self, guardrails: PromotionGuardrails | None = None) -> None:
        self.guardrails = guardrails or PromotionGuardrails()

    def assess(
        self,
        candidate_policy: str,
        comparisons: tuple[PolicyComparison, ...],
        stabilities: tuple[StabilityAssessment, ...],
        overlaps: tuple[OverlapFinding, ...],
        decisions: tuple[ComponentWeightDecision, ...],
    ) -> PromotionAssessment:
        by_partition = {item.partition: item for item in comparisons}
        required = (
            EvidencePartition.VALIDATION,
            EvidencePartition.HOLDOUT,
            EvidencePartition.FORWARD_OBSERVED,
        )
        missing = [
            partition.value for partition in required if partition not in by_partition
        ]
        if missing:
            return PromotionAssessment(
                candidate_policy=candidate_policy,
                decision=PromotionDecision.MORE_EVIDENCE,
                blockers=("missing required partitions: " + ", ".join(missing),),
                supporting_evidence=(),
                required_next_step=(
                    "collect validation, holdout, and forward-observed outcomes"
                ),
            )
        blockers: list[str] = []
        support: list[str] = []
        for partition in required:
            comparison = by_partition[partition]
            self._check_comparison(comparison, blockers, support)
        severe_overlap = any(
            item.redundancy_class
            in {RedundancyClass.HIGHLY_REDUNDANT, RedundancyClass.SAME_SOURCE}
            for item in overlaps
        )
        if severe_overlap:
            blockers.append("overlap analysis identifies double-counting")
        unstable = tuple(
            item
            for item in stabilities
            if item.classification in {StabilityClass.UNSTABLE, StabilityClass.NEGATIVE}
        )
        if unstable:
            blockers.append("one or more component revisions are unstable or negative")
        conditional = any(
            item.classification is StabilityClass.CONDITIONAL for item in stabilities
        )
        increased_components = {
            item.component
            for item in decisions
            if item.decision is ComponentDecisionState.INCREASE_WEIGHT
        }
        if increased_components and any(
            item.redundancy_class
            in {RedundancyClass.HIGHLY_REDUNDANT, RedundancyClass.SAME_SOURCE}
            and (
                item.component_a in increased_components
                or item.component_b in increased_components
            )
            for item in overlaps
        ):
            blockers.append("an increased component is not uniquely informative")
        if blockers:
            decision = (
                PromotionDecision.CONDITIONAL_ONLY
                if conditional and not any("holdout" in blocker for blocker in blockers)
                else PromotionDecision.REJECT
            )
            return PromotionAssessment(
                candidate_policy=candidate_policy,
                decision=decision,
                blockers=tuple(dict.fromkeys(blockers)),
                supporting_evidence=tuple(support),
                required_next_step=(
                    "retain as conditional research policy"
                    if decision is PromotionDecision.CONDITIONAL_ONLY
                    else "reject candidate and inspect failed evidence gates"
                ),
            )
        return PromotionAssessment(
            candidate_policy=candidate_policy,
            decision=PromotionDecision.PROMOTE_TO_POLICY_REVIEW,
            blockers=(),
            supporting_evidence=tuple(support),
            required_next_step="human policy review; no automatic deployment",
        )

    def _check_comparison(
        self,
        comparison: PolicyComparison,
        blockers: list[str],
        support: list[str],
    ) -> None:
        label = comparison.partition.value.lower()
        if (
            comparison.candidate.trade_count
            < self.guardrails.minimum_trades_per_partition
        ):
            blockers.append(f"{label} sample is below the promotion minimum")
        if comparison.symbol_count < self.guardrails.minimum_symbols:
            blockers.append(f"{label} improvement lacks symbol diversity")
        if comparison.sector_count < self.guardrails.minimum_sectors:
            blockers.append(f"{label} improvement lacks sector diversity")
        if comparison.candidate.expectancy <= comparison.baseline.expectancy:
            blockers.append(f"{label} expectancy did not improve")
        else:
            support.append(f"{label} expectancy improved")
        baseline_pf = comparison.baseline.profit_factor
        candidate_pf = comparison.candidate.profit_factor
        if baseline_pf is None or candidate_pf is None or candidate_pf < baseline_pf:
            blockers.append(f"{label} profit factor is unavailable or worse")
        if comparison.candidate.max_drawdown > (
            comparison.baseline.max_drawdown
            * (Decimal("1") + self.guardrails.maximum_drawdown_worsening)
        ):
            blockers.append(f"{label} drawdown materially worsened")
        baseline_costs = comparison.baseline.transaction_costs
        candidate_costs = comparison.candidate.transaction_costs
        if baseline_costs is None or candidate_costs is None:
            blockers.append(f"{label} transaction-cost comparison is unavailable")
        elif candidate_costs > (
            baseline_costs * (Decimal("1") + self.guardrails.maximum_cost_worsening)
        ):
            blockers.append(f"{label} transaction costs materially worsened")
        if comparison.candidate.sector_concentration > (
            comparison.baseline.sector_concentration
            + self.guardrails.maximum_concentration_worsening
        ):
            blockers.append(f"{label} sector concentration materially worsened")
        if comparison.candidate.setup_concentration > (
            comparison.baseline.setup_concentration
            + self.guardrails.maximum_concentration_worsening
        ):
            blockers.append(f"{label} setup concentration materially worsened")


class PolicyComparisonEngine:
    def compare(
        self,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        *,
        baseline_policy: str,
        candidate_policy: str,
        partition: EvidencePartition,
    ) -> PolicyComparison | None:
        baseline = tuple(
            item
            for item in evidence
            if item.policy_version == baseline_policy and item.partition is partition
        )
        candidate = tuple(
            item
            for item in evidence
            if item.policy_version == candidate_policy and item.partition is partition
        )
        if not baseline or not candidate:
            return None
        return PolicyComparison(
            baseline_policy=baseline_policy,
            candidate_policy=candidate_policy,
            partition=partition,
            baseline=_performance(baseline),
            candidate=_performance(candidate),
            symbol_count=len({item.symbol for item in candidate}),
            sector_count=len({item.sector for item in candidate}),
            setup_count=len({item.setup_family for item in candidate}),
        )


def _performance(
    evidence: tuple[CompletedOutcomeEvidence, ...],
) -> ResearchPerformance:
    returns = tuple(item.realized_r_multiple for item in evidence)
    winners = tuple(value for value in returns if value > Decimal("0"))
    losers = tuple(value for value in returns if value <= Decimal("0"))
    gains = sum(winners, start=Decimal("0"))
    losses = abs(sum(losers, start=Decimal("0")))
    cumulative = Decimal("0")
    peak = Decimal("0")
    drawdown = Decimal("0")
    for item in sorted(evidence, key=lambda value: (value.decision_date, value.symbol)):
        cumulative += item.realized_r_multiple
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    holding_days = tuple(
        Decimal((item.exit_date - item.decision_date).days)
        for item in evidence
        if item.exit_date is not None
    )
    sector_counts = Counter(item.sector for item in evidence)
    setup_counts = Counter(item.setup_family for item in evidence)
    count = Decimal(len(evidence))
    return ResearchPerformance(
        expectancy=sum(returns, start=Decimal("0")) / count,
        win_rate=Decimal(len(winners)) / count,
        average_winner_r=(gains / Decimal(len(winners))) if winners else Decimal("0"),
        average_loser_r=(sum(losers, start=Decimal("0")) / Decimal(len(losers)))
        if losers
        else Decimal("0"),
        profit_factor=gains / losses if losses else None,
        max_drawdown=drawdown,
        trade_count=len(evidence),
        average_holding_period=(
            sum(holding_days, start=Decimal("0")) / Decimal(len(holding_days))
            if holding_days
            else Decimal("0")
        ),
        turnover=sum(
            (abs(item.realized_return) for item in evidence), start=Decimal("0")
        ),
        transaction_costs=sum(
            (item.transaction_costs for item in evidence), start=Decimal("0")
        ),
        sector_concentration=Decimal(max(sector_counts.values())) / count,
        setup_concentration=Decimal(max(setup_counts.values())) / count,
    )


__all__ = [
    "CandidateWeightPromotionEngine",
    "PolicyComparisonEngine",
    "PromotionGuardrails",
]
