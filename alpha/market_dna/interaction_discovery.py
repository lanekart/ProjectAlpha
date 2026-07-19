from __future__ import annotations

from collections import Counter
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
from math import asin, erfc, sqrt

from alpha.market_dna.effect_size_engine import condition_matches
from alpha.market_dna.lineage_analysis import LineageAnalysis
from alpha.market_dna.models import (
    CohortSummary,
    DNAPatternStatus,
    FeatureAudit,
    FeatureCondition,
    FeatureFinding,
    FeatureSnapshot,
    InteractionFinding,
)


class InteractionDiscovery:
    """Bounded pair discovery from fixed-grid individual conditions."""

    def __init__(self, *, lineage: LineageAnalysis | None = None) -> None:
        self.lineage = lineage or LineageAnalysis()

    def discover(
        self,
        *,
        cohort: CohortSummary,
        snapshots: tuple[FeatureSnapshot, ...],
        findings: tuple[FeatureFinding, ...],
        audits: tuple[FeatureAudit, ...],
        minimum_cell: int = 20,
        maximum_interactions: int = 50,
    ) -> tuple[InteractionFinding, ...]:
        if minimum_cell < 2 or maximum_interactions < 1:
            raise ValueError("interaction bounds must be positive")
        definitions = {item.feature.feature_id: item.feature for item in audits}
        candidates = sorted(
            (
                item
                for item in findings
                if item.cohort_id == cohort.definition.cohort_id
                and item.cohort_match_count >= minimum_cell
                and item.baseline_match_count >= minimum_cell
            ),
            key=lambda item: (
                item.raw_p_value if item.raw_p_value is not None else Decimal("1"),
                -(
                    abs(item.effect_size)
                    if item.effect_size is not None
                    else Decimal("0")
                ),
                item.condition.canonical_key,
            ),
        )[:12]
        pairs = tuple(
            pair
            for pair in combinations(candidates, 2)
            if pair[0].condition.feature_id != pair[1].condition.feature_id
        )[:maximum_interactions]
        cohort_ids = frozenset(cohort.candidate_ids)
        cohort_rows = tuple(
            item for item in snapshots if item.candidate_id in cohort_ids
        )
        baseline_rows = tuple(
            item for item in snapshots if item.candidate_id not in cohort_ids
        )
        output: list[InteractionFinding] = []
        for left, right in pairs:
            conditions = tuple(
                sorted(
                    (left.condition, right.condition),
                    key=lambda item: item.canonical_key,
                )
            )
            treatment = tuple(
                item for item in cohort_rows if _matches_all(conditions, item)
            )
            baseline = tuple(
                item for item in baseline_rows if _matches_all(conditions, item)
            )
            first = Decimal(len(treatment)) / Decimal(len(cohort_rows))
            second = Decimal(len(baseline)) / Decimal(len(baseline_rows))
            insufficient = len(treatment) < minimum_cell or len(baseline) < minimum_cell
            lineage_penalty = self.lineage.interaction_is_confounded(
                conditions, definitions
            )
            interaction_id = (
                "DNA_INTERACTION_"
                + sha256(
                    (
                        cohort.definition.cohort_id
                        + "|"
                        + "|".join(item.canonical_key for item in conditions)
                    ).encode()
                )
                .hexdigest()[:16]
                .upper()
            )
            output.append(
                InteractionFinding(
                    interaction_id=interaction_id,
                    cohort_id=cohort.definition.cohort_id,
                    conditions=conditions,
                    sample_size=len(treatment),
                    baseline_size=len(baseline),
                    enrichment_ratio=(
                        None
                        if second == 0
                        else (first / second).quantize(Decimal("0.0001"))
                    ),
                    effect_size=Decimal(
                        str(2 * (asin(sqrt(float(first))) - asin(sqrt(float(second)))))
                    ).quantize(Decimal("0.0001")),
                    raw_p_value=_p_value(
                        len(treatment),
                        len(cohort_rows),
                        len(baseline),
                        len(baseline_rows),
                    ),
                    adjusted_p_value=None,
                    fold_consistency_pct=_fold_consistency(
                        conditions, cohort_rows, baseline_rows, first >= second
                    ),
                    symbol_concentration_pct=_top_symbol_share(treatment),
                    lineage_penalty=lineage_penalty,
                    status=(
                        DNAPatternStatus.INSUFFICIENT_SAMPLE
                        if insufficient
                        else DNAPatternStatus.LINEAGE_CONFOUNDED
                        if lineage_penalty
                        else DNAPatternStatus.MULTIPLE_TESTING_FAILURE
                    ),
                )
            )
        return tuple(output)


def _matches_all(
    conditions: tuple[FeatureCondition, ...], item: FeatureSnapshot
) -> bool:
    return all(condition_matches(condition, item) for condition in conditions)


def _p_value(a: int, first_n: int, c: int, second_n: int) -> Decimal | None:
    if first_n == 0 or second_n == 0:
        return None
    pooled = (a + c) / (first_n + second_n)
    variance = pooled * (1 - pooled) * (1 / first_n + 1 / second_n)
    if variance == 0:
        return Decimal("1") if a / first_n == c / second_n else Decimal("0")
    z_score = abs(a / first_n - c / second_n) / sqrt(variance)
    return Decimal(str(erfc(z_score / sqrt(2)))).quantize(Decimal("0.000001"))


def _fold_consistency(
    conditions: tuple[FeatureCondition, ...],
    cohort: tuple[FeatureSnapshot, ...],
    baseline: tuple[FeatureSnapshot, ...],
    enriched: bool,
) -> Decimal | None:
    years = sorted(
        {item.candidate_timestamp.year for item in cohort}.intersection(
            item.candidate_timestamp.year for item in baseline
        )
    )
    consistent = 0
    eligible = 0
    for year in years:
        left = tuple(item for item in cohort if item.candidate_timestamp.year == year)
        right = tuple(
            item for item in baseline if item.candidate_timestamp.year == year
        )
        if len(left) < 3 or len(right) < 3:
            continue
        first = sum(_matches_all(conditions, item) for item in left) / len(left)
        second = sum(_matches_all(conditions, item) for item in right) / len(right)
        eligible += 1
        consistent += (first >= second) if enriched else (first < second)
    if eligible < 3:
        return None
    return (Decimal(consistent) / Decimal(eligible) * Decimal("100")).quantize(
        Decimal("0.01")
    )


def _top_symbol_share(rows: tuple[FeatureSnapshot, ...]) -> Decimal | None:
    if not rows:
        return None
    count = Counter(item.symbol for item in rows).most_common(1)[0][1]
    return (Decimal(count) / Decimal(len(rows)) * Decimal("100")).quantize(
        Decimal("0.01")
    )


__all__ = ["InteractionDiscovery"]
