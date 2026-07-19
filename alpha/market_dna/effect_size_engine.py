from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from math import asin, erfc, sqrt

from alpha.market_dna.lineage_analysis import LineageAnalysis
from alpha.market_dna.models import (
    CohortSummary,
    ConditionOperator,
    FeatureAudit,
    FeatureCondition,
    FeatureFinding,
    FeatureKind,
    FeatureSnapshot,
    PatternDirection,
    TemporalStability,
)

_FOUR = Decimal("0.0001")


class EffectSizeEngine:
    """Fixed-grid feature enrichment with effect sizes and concentration checks."""

    def __init__(self, *, lineage: LineageAnalysis | None = None) -> None:
        self.lineage = lineage or LineageAnalysis()

    def conditions(
        self,
        audit: FeatureAudit,
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> tuple[FeatureCondition, ...]:
        if not audit.discovery_permitted:
            return ()
        feature = audit.feature
        if feature.kind is FeatureKind.CONTINUOUS:
            operator = (
                ConditionOperator.LESS_THAN_OR_EQUAL
                if feature.feature_id == "stop_distance_pct"
                else ConditionOperator.GREATER_THAN_OR_EQUAL
            )
            return tuple(
                FeatureCondition(feature.feature_id, operator, str(value))
                for value in feature.threshold_grid
            )
        values = sorted(
            {
                value
                for item in snapshots
                if (value := item.feature_values.get(feature.feature_id)) is not None
                and value.lower() != "unavailable"
            }
        )
        return tuple(
            FeatureCondition(feature.feature_id, ConditionOperator.EQUAL, value)
            for value in values[:20]
        )

    def evaluate(
        self,
        *,
        cohort: CohortSummary,
        scope: str,
        snapshots: tuple[FeatureSnapshot, ...],
        audits: tuple[FeatureAudit, ...],
        matched_candidate_ids: frozenset[str] | None = None,
        matched_baseline_ids: frozenset[str] | None = None,
    ) -> tuple[FeatureFinding, ...]:
        cohort_ids = frozenset(cohort.candidate_ids)
        cohort_rows = tuple(
            item
            for item in snapshots
            if item.candidate_id in cohort_ids
            and (
                matched_candidate_ids is None
                or item.candidate_id in matched_candidate_ids
            )
        )
        baseline_rows = tuple(
            item
            for item in snapshots
            if item.candidate_id not in cohort_ids
            and (
                matched_baseline_ids is None
                or item.candidate_id in matched_baseline_ids
            )
        )
        output: list[FeatureFinding] = []
        for audit in audits:
            if _cohort_defining_feature(
                cohort.definition.cohort_id, audit.feature.feature_id
            ):
                continue
            for condition in self.conditions(audit, snapshots):
                output.append(
                    self.evaluate_condition(
                        cohort_id=cohort.definition.cohort_id,
                        scope=scope,
                        condition=condition,
                        cohort_rows=cohort_rows,
                        baseline_rows=baseline_rows,
                        lineage_risks=self.lineage.risks_for_feature(audit.feature),
                    )
                )
        return tuple(output)

    def evaluate_condition(
        self,
        *,
        cohort_id: str,
        scope: str,
        condition: FeatureCondition,
        cohort_rows: tuple[FeatureSnapshot, ...],
        baseline_rows: tuple[FeatureSnapshot, ...],
        lineage_risks: tuple[str, ...] = (),
    ) -> FeatureFinding:
        cohort_matches = tuple(
            item for item in cohort_rows if condition_matches(condition, item)
        )
        baseline_matches = tuple(
            item for item in baseline_rows if condition_matches(condition, item)
        )
        first = _ratio(len(cohort_matches), len(cohort_rows))
        second = _ratio(len(baseline_matches), len(baseline_rows))
        direction = (
            PatternDirection.ENRICHED
            if first is not None and second is not None and first >= second
            else PatternDirection.DEPLETED
        )
        fold_consistency, stability = _temporal(
            condition, cohort_rows, baseline_rows, direction
        )
        finding_id = (
            "DNA_FINDING_"
            + sha256(f"{cohort_id}|{scope}|{condition.canonical_key}".encode())
            .hexdigest()[:16]
            .upper()
        )
        return FeatureFinding(
            finding_id=finding_id,
            cohort_id=cohort_id,
            scope=scope,
            condition=condition,
            cohort_count=len(cohort_rows),
            baseline_count=len(baseline_rows),
            cohort_match_count=len(cohort_matches),
            baseline_match_count=len(baseline_matches),
            cohort_prevalence_pct=_pct(len(cohort_matches), len(cohort_rows)),
            baseline_prevalence_pct=_pct(len(baseline_matches), len(baseline_rows)),
            enrichment_ratio=_enrichment(first, second),
            odds_ratio=_odds_ratio(
                len(cohort_matches),
                len(cohort_rows) - len(cohort_matches),
                len(baseline_matches),
                len(baseline_rows) - len(baseline_matches),
            ),
            risk_ratio=_enrichment(first, second),
            effect_size=_cohen_h(first, second),
            confidence_interval_low=_ci(
                first, second, len(cohort_rows), len(baseline_rows)
            )[0],
            confidence_interval_high=_ci(
                first, second, len(cohort_rows), len(baseline_rows)
            )[1],
            raw_p_value=_proportion_p(
                len(cohort_matches),
                len(cohort_rows),
                len(baseline_matches),
                len(baseline_rows),
            ),
            adjusted_p_value=None,
            direction=direction,
            fold_consistency_pct=fold_consistency,
            years_represented=len(
                {item.candidate_timestamp.year for item in cohort_matches}
            ),
            symbols_represented=len({item.symbol for item in cohort_matches}),
            symbol_concentration_pct=_top_share(item.symbol for item in cohort_matches),
            period_concentration_pct=_top_share(
                str(item.candidate_timestamp.year) for item in cohort_matches
            ),
            winner_concentration_pct=_winner_concentration(cohort_matches),
            temporal_stability=stability,
            evidence_class=(
                cohort_rows[0].evidence_class
                if cohort_rows
                else baseline_rows[0].evidence_class
            ),
            lineage_risks=lineage_risks,
        )


def condition_matches(condition: FeatureCondition, item: FeatureSnapshot) -> bool:
    value = item.feature_values.get(condition.feature_id)
    if value is None or value.lower() == "unavailable":
        return False
    if condition.operator is ConditionOperator.EQUAL:
        return value == condition.value
    if condition.operator is ConditionOperator.IS_TRUE:
        return value == "true"
    if condition.operator is ConditionOperator.IS_FALSE:
        return value == "false"
    try:
        observed = Decimal(value)
        threshold = Decimal(condition.value)
    except InvalidOperation:
        return False
    if condition.operator is ConditionOperator.GREATER_THAN_OR_EQUAL:
        return observed >= threshold
    return observed <= threshold


def _cohort_defining_feature(cohort_id: str, feature_id: str) -> bool:
    if cohort_id in {
        "PROFITABLE_REJECTED",
        "APPROVED_PROFITABLE",
        "APPROVED_UNPROFITABLE",
    }:
        return feature_id == "raw_approved"
    if cohort_id == "MISSED_ENTRY_WINNERS":
        return feature_id == "entry_timing_state"
    return False


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _pct(numerator: int, denominator: int) -> Decimal | None:
    ratio = _ratio(numerator, denominator)
    return None if ratio is None else (ratio * Decimal("100")).quantize(_FOUR)


def _enrichment(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    if first is None or second is None or second == 0:
        return None
    return (first / second).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _odds_ratio(a: int, b: int, c: int, d: int) -> Decimal | None:
    if a + b == 0 or c + d == 0:
        return None
    numerator = (Decimal(a) + Decimal("0.5")) * (Decimal(d) + Decimal("0.5"))
    denominator = (Decimal(b) + Decimal("0.5")) * (Decimal(c) + Decimal("0.5"))
    return (numerator / denominator).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _cohen_h(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    if first is None or second is None:
        return None
    value = 2 * (asin(sqrt(float(first))) - asin(sqrt(float(second))))
    return Decimal(str(value)).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _ci(
    first: Decimal | None,
    second: Decimal | None,
    first_n: int,
    second_n: int,
) -> tuple[Decimal | None, Decimal | None]:
    if first is None or second is None or first_n == 0 or second_n == 0:
        return None, None
    difference = float(first - second)
    error = 1.96 * sqrt(
        float(first * (1 - first)) / first_n + float(second * (1 - second)) / second_n
    )
    return (
        Decimal(str(difference - error)).quantize(_FOUR),
        Decimal(str(difference + error)).quantize(_FOUR),
    )


def _proportion_p(a: int, first_n: int, c: int, second_n: int) -> Decimal | None:
    if first_n == 0 or second_n == 0:
        return None
    pooled = (a + c) / (first_n + second_n)
    variance = pooled * (1 - pooled) * (1 / first_n + 1 / second_n)
    if variance == 0:
        return Decimal("1") if a / first_n == c / second_n else Decimal("0")
    statistic = abs(a / first_n - c / second_n) / sqrt(variance)
    return Decimal(str(erfc(statistic / sqrt(2)))).quantize(Decimal("0.000001"))


def _top_share(values: Iterable[object]) -> Decimal | None:
    materialized = tuple(str(item) for item in values)
    if not materialized:
        return None
    count = Counter(materialized).most_common(1)[0][1]
    return _pct(count, len(materialized))


def _winner_concentration(rows: tuple[FeatureSnapshot, ...]) -> Decimal | None:
    positives = tuple(max(Decimal("0"), item.net_return_pct) for item in rows)
    total = sum(positives, start=Decimal("0"))
    if total == 0:
        return None
    return (max(positives) / total * Decimal("100")).quantize(_FOUR)


def _temporal(
    condition: FeatureCondition,
    cohort: tuple[FeatureSnapshot, ...],
    baseline: tuple[FeatureSnapshot, ...],
    direction: PatternDirection,
) -> tuple[Decimal | None, TemporalStability]:
    years = sorted(
        {item.candidate_timestamp.year for item in cohort}.intersection(
            item.candidate_timestamp.year for item in baseline
        )
    )
    signs: list[bool] = []
    effects: list[Decimal] = []
    for year in years:
        left = tuple(item for item in cohort if item.candidate_timestamp.year == year)
        right = tuple(
            item for item in baseline if item.candidate_timestamp.year == year
        )
        if len(left) < 3 or len(right) < 3:
            continue
        first = _ratio(
            sum(condition_matches(condition, item) for item in left), len(left)
        )
        second = _ratio(
            sum(condition_matches(condition, item) for item in right), len(right)
        )
        if first is None or second is None:
            continue
        effects.append(first - second)
        signs.append(
            (first >= second)
            if direction is PatternDirection.ENRICHED
            else (first < second)
        )
    if len(signs) < 3:
        return None, TemporalStability.INSUFFICIENT_EVIDENCE
    consistency = _pct(sum(signs), len(signs))
    assert consistency is not None
    if consistency >= Decimal("67"):
        first_half = sum(effects[: max(1, len(effects) // 2)], start=Decimal("0"))
        second_half = sum(effects[len(effects) // 2 :], start=Decimal("0"))
        if abs(second_half) < abs(first_half) * Decimal("0.5"):
            return consistency, TemporalStability.WEAKENING
        if abs(first_half) < abs(second_half) * Decimal("0.5"):
            return consistency, TemporalStability.EMERGING
        return consistency, TemporalStability.STABLE
    return consistency, TemporalStability.UNSTABLE


__all__ = ["EffectSizeEngine", "condition_matches"]
