from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from math import erfc, sqrt
from statistics import mean, median, stdev

from alpha.market_dna.feature_enrichment import numeric_value
from alpha.market_dna.models import (
    DistributionComparison,
    FeatureAudit,
    FeatureKind,
    FeatureSnapshot,
)


class DistributionAnalysis:
    """Compare continuous feature distributions without selecting thresholds."""

    def compare(
        self,
        *,
        cohort_id: str,
        scope: str,
        cohort_ids: frozenset[str],
        snapshots: tuple[FeatureSnapshot, ...],
        audits: tuple[FeatureAudit, ...],
    ) -> tuple[DistributionComparison, ...]:
        output: list[DistributionComparison] = []
        for audit in audits:
            if (
                not audit.discovery_permitted
                or audit.feature.kind is not FeatureKind.CONTINUOUS
            ):
                continue
            cohort = tuple(
                value
                for item in snapshots
                if item.candidate_id in cohort_ids
                if (value := numeric_value(item, audit.feature.feature_id)) is not None
            )
            baseline = tuple(
                value
                for item in snapshots
                if item.candidate_id not in cohort_ids
                if (value := numeric_value(item, audit.feature.feature_id)) is not None
            )
            output.append(
                _comparison(
                    cohort_id,
                    scope,
                    audit.feature.feature_id,
                    cohort,
                    baseline,
                )
            )
        return tuple(output)


def _comparison(
    cohort_id: str,
    scope: str,
    feature_id: str,
    cohort: tuple[Decimal, ...],
    baseline: tuple[Decimal, ...],
) -> DistributionComparison:
    effect = _cohen_d(cohort, baseline)
    return DistributionComparison(
        cohort_id=cohort_id,
        scope=scope,
        feature_id=feature_id,
        cohort_count=len(cohort),
        baseline_count=len(baseline),
        cohort_mean=_mean(cohort),
        baseline_mean=_mean(baseline),
        cohort_median=_median(cohort),
        baseline_median=_median(baseline),
        standardised_effect_size=effect,
        distribution_overlap=(
            None
            if effect is None
            else max(
                Decimal("0"),
                Decimal("1") - min(Decimal("1"), abs(effect) / Decimal("3")),
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        ),
        raw_p_value=_welch_normal_p(cohort, baseline),
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, start=Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _cohen_d(first: tuple[Decimal, ...], second: tuple[Decimal, ...]) -> Decimal | None:
    if len(first) < 2 or len(second) < 2:
        return None
    left = tuple(float(item) for item in first)
    right = tuple(float(item) for item in second)
    pooled_n = len(left) + len(right) - 2
    variance = (
        (len(left) - 1) * stdev(left) ** 2 + (len(right) - 1) * stdev(right) ** 2
    ) / pooled_n
    if variance == 0:
        return Decimal("0")
    value = (mean(left) - mean(right)) / sqrt(variance)
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _welch_normal_p(
    first: tuple[Decimal, ...], second: tuple[Decimal, ...]
) -> Decimal | None:
    if len(first) < 2 or len(second) < 2:
        return None
    left = tuple(float(item) for item in first)
    right = tuple(float(item) for item in second)
    standard_error = sqrt(stdev(left) ** 2 / len(left) + stdev(right) ** 2 / len(right))
    if standard_error == 0:
        return Decimal("1") if mean(left) == mean(right) else Decimal("0")
    z_score = abs(mean(left) - mean(right)) / standard_error
    return Decimal(str(erfc(z_score / sqrt(2)))).quantize(Decimal("0.000001"))


__all__ = ["DistributionAnalysis"]
