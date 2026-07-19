from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    ContributionEstimate,
    EvidencePartition,
    StabilityAssessment,
    StabilityClass,
)


class ContributionStabilityEngine:
    def __init__(self, *, minimum_sample_size: int = 10) -> None:
        self.minimum_sample_size = minimum_sample_size

    def analyze(
        self,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        contributions: tuple[ContributionEstimate, ...],
    ) -> tuple[StabilityAssessment, ...]:
        contribution_by_component = {item.component: item for item in contributions}
        partition_ranks = _partition_ranks(evidence)
        return tuple(
            self._component(
                component,
                evidence,
                contribution_by_component[component],
                partition_ranks,
            )
            for component in AlphaComponent
        )

    def _component(
        self,
        component: AlphaComponent,
        evidence: tuple[CompletedOutcomeEvidence, ...],
        contribution: ContributionEstimate,
        partition_ranks: dict[str, dict[AlphaComponent, int]],
    ) -> StabilityAssessment:
        available = tuple(
            item for item in evidence if item.score_for(component) is not None
        )
        overall = contribution.marginal_contribution
        partition_slopes = _slopes_by(available, component, "partition")
        sector_slopes = _slopes_by(available, component, "sector")
        setup_slopes = _slopes_by(available, component, "setup")
        regime_slopes = _slopes_by(available, component, "regime")
        horizon_slopes = _slopes_by(available, component, "horizon")
        era_slopes = _slopes_by(available, component, "era")
        directional = _sign_consistency(tuple(partition_slopes.values()), overall)
        magnitude = _magnitude_stability(tuple(partition_slopes.values()))
        rank = _rank_stability(component, partition_ranks)
        holdout = _partition_consistency(
            partition_slopes, EvidencePartition.HOLDOUT, overall
        )
        forward = _partition_consistency(
            partition_slopes, EvidencePartition.FORWARD_OBSERVED, overall
        )
        sector = _sign_consistency(tuple(sector_slopes.values()), overall)
        setup = _sign_consistency(tuple(setup_slopes.values()), overall)
        regime = _sign_consistency(tuple(regime_slopes.values()), overall)
        horizon = _sign_consistency(tuple(horizon_slopes.values()), overall)
        era = _sign_consistency(tuple(era_slopes.values()), overall)
        classification = self._classify(
            len(available), overall, directional, holdout, setup, regime
        )
        notes = []
        if holdout is None:
            notes.append("holdout contribution unavailable")
        if forward is None:
            notes.append("forward-observed contribution unavailable")
        if classification is StabilityClass.CONDITIONAL:
            notes.append("contribution direction differs across setup or regime")
        return StabilityAssessment(
            component=component,
            sample_size=len(available),
            directional_stability=directional,
            magnitude_stability=magnitude,
            rank_stability=rank,
            sector_stability=sector,
            setup_stability=setup,
            regime_stability=regime,
            horizon_stability=horizon,
            era_stability=era,
            holdout_consistency=holdout,
            forward_consistency=forward,
            classification=classification,
            evidence_notes=tuple(notes),
        )

    def _classify(
        self,
        sample_size: int,
        overall: Decimal | None,
        directional: Decimal | None,
        holdout: bool | None,
        setup: Decimal | None,
        regime: Decimal | None,
    ) -> StabilityClass:
        if sample_size < self.minimum_sample_size or overall is None:
            return StabilityClass.INSUFFICIENT_EVIDENCE
        if overall < Decimal("0") and holdout is not True:
            return StabilityClass.NEGATIVE
        if holdout is False:
            return StabilityClass.UNSTABLE
        if (setup is not None and setup < Decimal("0.60")) or (
            regime is not None and regime < Decimal("0.60")
        ):
            return StabilityClass.CONDITIONAL
        if directional is not None and directional >= Decimal("0.75") and holdout:
            return StabilityClass.ROBUST
        if directional is not None and directional >= Decimal("0.60"):
            return StabilityClass.MODERATELY_STABLE
        return StabilityClass.UNSTABLE


def _slopes_by(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    component: AlphaComponent,
    dimension: str,
) -> dict[str, Decimal]:
    groups: dict[str, list[CompletedOutcomeEvidence]] = defaultdict(list)
    for item in evidence:
        key = {
            "partition": item.partition.value,
            "sector": item.sector,
            "setup": item.setup_family,
            "regime": item.market_regime,
            "horizon": item.holding_horizon,
            "era": str((item.decision_date.year // 5) * 5),
        }[dimension]
        groups[key].append(item)
    return {
        key: slope
        for key, items in groups.items()
        if len(items) >= 3 and (slope := _slope(tuple(items), component)) is not None
    }


def _slope(
    evidence: tuple[CompletedOutcomeEvidence, ...], component: AlphaComponent
) -> Decimal | None:
    x = [item.score_for(component) or Decimal("0") for item in evidence]
    y = [item.realized_r_multiple for item in evidence]
    x_mean = _mean(tuple(x))
    y_mean = _mean(tuple(y))
    denominator = sum(((value - x_mean) ** 2 for value in x), start=Decimal("0"))
    if denominator == Decimal("0"):
        return None
    return (
        sum(
            ((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True)),
            start=Decimal("0"),
        )
        / denominator
    )


def _sign_consistency(
    values: tuple[Decimal, ...], reference: Decimal | None
) -> Decimal | None:
    if not values or reference is None or reference == Decimal("0"):
        return None
    matching = sum(1 for value in values if (value >= 0) == (reference >= 0))
    return Decimal(matching) / Decimal(len(values))


def _magnitude_stability(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    absolute_mean = _mean(tuple(abs(value) for value in values))
    if absolute_mean == Decimal("0"):
        return Decimal("1")
    mean = _mean(values)
    variance = _mean(tuple((value - mean) ** 2 for value in values))
    coefficient = variance.sqrt() / absolute_mean
    return max(Decimal("0"), Decimal("1") - min(Decimal("1"), coefficient))


def _partition_consistency(
    values: dict[str, Decimal],
    partition: EvidencePartition,
    reference: Decimal | None,
) -> bool | None:
    value = values.get(partition.value)
    if value is None or reference is None or reference == Decimal("0"):
        return None
    return (value >= Decimal("0")) == (reference >= Decimal("0"))


def _partition_ranks(
    evidence: tuple[CompletedOutcomeEvidence, ...],
) -> dict[str, dict[AlphaComponent, int]]:
    grouped: dict[str, list[CompletedOutcomeEvidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.partition.value].append(item)
    ranks: dict[str, dict[AlphaComponent, int]] = {}
    for partition, items in grouped.items():
        slopes = {
            component: _slope(tuple(items), component)
            for component in AlphaComponent
            if all(item.score_for(component) is not None for item in items)
        }
        valid = sorted(
            (
                (component, value)
                for component, value in slopes.items()
                if value is not None
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        ranks[partition] = {
            component: index for index, (component, _) in enumerate(valid)
        }
    return ranks


def _rank_stability(
    component: AlphaComponent, ranks: dict[str, dict[AlphaComponent, int]]
) -> Decimal | None:
    values = [rank[component] for rank in ranks.values() if component in rank]
    if len(values) < 2:
        return None
    spread = max(values) - min(values)
    return max(
        Decimal("0"),
        Decimal("1") - Decimal(spread) / Decimal(max(1, len(AlphaComponent) - 1)),
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return (
        sum(values, start=Decimal("0")) / Decimal(len(values))
        if values
        else Decimal("0")
    )


__all__ = ["ContributionStabilityEngine"]
