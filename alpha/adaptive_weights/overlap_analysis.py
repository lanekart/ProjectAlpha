from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal
from itertools import combinations

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    OverlapFinding,
    RedundancyClass,
)


class IndicatorOverlapEngine:
    def __init__(
        self,
        *,
        minimum_sample_size: int = 5,
        partial_correlation: Decimal = Decimal("0.65"),
        high_correlation: Decimal = Decimal("0.85"),
    ) -> None:
        self.minimum_sample_size = minimum_sample_size
        self.partial_correlation = partial_correlation
        self.high_correlation = high_correlation

    def analyze(
        self, evidence: tuple[CompletedOutcomeEvidence, ...]
    ) -> tuple[OverlapFinding, ...]:
        return tuple(
            self._pair(evidence, component_a, component_b)
            for component_a, component_b in combinations(AlphaComponent, 2)
        )

    def _pair(
        self,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        component_a: AlphaComponent,
        component_b: AlphaComponent,
    ) -> OverlapFinding:
        paired = tuple(
            item
            for item in evidence
            if item.score_for(component_a) is not None
            and item.score_for(component_b) is not None
        )
        lineages_a = {item.lineage_for(component_a) for item in paired}
        lineages_b = {item.lineage_for(component_b) for item in paired}
        same_source = (
            bool(paired) and lineages_a == lineages_b and lineages_a != {"unavailable"}
        )
        correlation = _correlation(
            tuple(item.score_for(component_a) or Decimal("0") for item in paired),
            tuple(item.score_for(component_b) or Decimal("0") for item in paired),
        )
        candidate_overlap = _active_overlap(paired, component_a, component_b)
        approval_overlap = _active_overlap(
            tuple(item for item in paired if item.approved),
            component_a,
            component_b,
        )
        mutual_information = _binary_mutual_information(
            paired, component_a, component_b
        )
        setup_redundancy = _group_redundancy(
            paired, component_a, component_b, group_by="setup"
        )
        regime_redundancy = _group_redundancy(
            paired, component_a, component_b, group_by="regime"
        )
        classification = self._classify(
            len(paired), same_source, correlation, candidate_overlap
        )
        return OverlapFinding(
            component_a=component_a,
            component_b=component_b,
            sample_size=len(paired),
            score_correlation=correlation,
            candidate_overlap=candidate_overlap,
            approval_overlap=approval_overlap,
            mutual_information=mutual_information,
            shared_source_lineage=same_source,
            setup_redundancy=setup_redundancy,
            regime_redundancy=regime_redundancy,
            redundancy_class=classification,
            recommended_action=_recommended_action(classification),
        )

    def _classify(
        self,
        sample_size: int,
        same_source: bool,
        correlation: Decimal | None,
        candidate_overlap: Decimal | None,
    ) -> RedundancyClass:
        if sample_size < self.minimum_sample_size:
            return RedundancyClass.INSUFFICIENT_EVIDENCE
        if same_source:
            return RedundancyClass.SAME_SOURCE
        absolute_correlation = abs(correlation or Decimal("0"))
        overlap = candidate_overlap or Decimal("0")
        if absolute_correlation >= self.high_correlation and overlap >= Decimal("0.80"):
            return RedundancyClass.HIGHLY_REDUNDANT
        if absolute_correlation >= self.partial_correlation or overlap >= Decimal(
            "0.70"
        ):
            return RedundancyClass.PARTIALLY_REDUNDANT
        return RedundancyClass.UNIQUE


def _correlation(x: tuple[Decimal, ...], y: tuple[Decimal, ...]) -> Decimal | None:
    if len(x) < 2 or len(x) != len(y):
        return None
    x_mean = sum(x, start=Decimal("0")) / Decimal(len(x))
    y_mean = sum(y, start=Decimal("0")) / Decimal(len(y))
    covariance = sum(
        ((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True)),
        start=Decimal("0"),
    )
    x_variance = sum(((value - x_mean) ** 2 for value in x), start=Decimal("0"))
    y_variance = sum(((value - y_mean) ** 2 for value in y), start=Decimal("0"))
    denominator = (x_variance * y_variance).sqrt()
    return covariance / denominator if denominator else None


def _active_overlap(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    component_a: AlphaComponent,
    component_b: AlphaComponent,
) -> Decimal | None:
    if not evidence:
        return None
    active_a = {
        item.recommendation_id
        for item in evidence
        if (item.score_for(component_a) or Decimal("0")) >= Decimal("0.50")
    }
    active_b = {
        item.recommendation_id
        for item in evidence
        if (item.score_for(component_b) or Decimal("0")) >= Decimal("0.50")
    }
    union = active_a | active_b
    if not union:
        return Decimal("0")
    return Decimal(len(active_a & active_b)) / Decimal(len(union))


def _binary_mutual_information(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    component_a: AlphaComponent,
    component_b: AlphaComponent,
) -> Decimal | None:
    if len(evidence) < 2:
        return None
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for item in evidence:
        a = int((item.score_for(component_a) or Decimal("0")) >= Decimal("0.50"))
        b = int((item.score_for(component_b) or Decimal("0")) >= Decimal("0.50"))
        counts[(a, b)] += 1
    total = len(evidence)
    mutual_information = 0.0
    for (a, b), count in counts.items():
        joint = count / total
        marginal_a = sum(value for (x, _), value in counts.items() if x == a) / total
        marginal_b = sum(value for (_, y), value in counts.items() if y == b) / total
        if joint > 0 and marginal_a > 0 and marginal_b > 0:
            mutual_information += joint * math.log2(joint / (marginal_a * marginal_b))
    return Decimal(str(round(mutual_information, 8)))


def _group_redundancy(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    component_a: AlphaComponent,
    component_b: AlphaComponent,
    *,
    group_by: str,
) -> Decimal | None:
    groups: dict[str, list[CompletedOutcomeEvidence]] = defaultdict(list)
    for item in evidence:
        key = item.setup_family if group_by == "setup" else item.market_regime
        groups[key].append(item)
    correlations = []
    for group in groups.values():
        if len(group) < 3:
            continue
        correlation = _correlation(
            tuple(item.score_for(component_a) or Decimal("0") for item in group),
            tuple(item.score_for(component_b) or Decimal("0") for item in group),
        )
        if correlation is not None:
            correlations.append(abs(correlation))
    return max(correlations) if correlations else None


def _recommended_action(classification: RedundancyClass) -> str:
    return {
        RedundancyClass.UNIQUE: "retain independent contribution",
        RedundancyClass.PARTIALLY_REDUNDANT: "apply overlap shrinkage",
        RedundancyClass.HIGHLY_REDUNDANT: "cap combined increase and ablate pair",
        RedundancyClass.SAME_SOURCE: "do not count as independent evidence",
        RedundancyClass.INSUFFICIENT_EVIDENCE: "collect matched overlap evidence",
    }[classification]


__all__ = ["IndicatorOverlapEngine"]
