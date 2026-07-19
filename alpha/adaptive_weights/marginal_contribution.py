from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from types import MappingProxyType

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    ContributionEstimate,
)

_RIDGE_PENALTY = Decimal("0.10")
_ITERATIONS = 80


class MarginalContributionEngine:
    """Transparent bounded contribution estimates on realised R multiples."""

    def analyze(
        self, evidence: tuple[CompletedOutcomeEvidence, ...]
    ) -> tuple[ContributionEstimate, ...]:
        complete = tuple(
            item
            for item in evidence
            if all(
                item.score_for(component) is not None for component in AlphaComponent
            )
        )
        coefficients = _ridge_coefficients(complete)
        full_error = _prediction_error(complete, coefficients)
        partition_coefficients = self._partition_coefficients(complete)
        estimates: list[ContributionEstimate] = []
        for component in AlphaComponent:
            available = tuple(
                item for item in evidence if item.score_for(component) is not None
            )
            partition_values = {
                partition: values[component]
                for partition, values in partition_coefficients.items()
                if component in values
            }
            interval_values = tuple(partition_values.values())
            without = _ridge_coefficients(complete, omitted=component)
            without_error = _prediction_error(complete, without)
            estimates.append(
                ContributionEstimate(
                    component=component,
                    standalone_contribution=_standalone_difference(
                        available, component
                    ),
                    marginal_contribution=coefficients.get(component),
                    conditional_contribution=_conditional_contribution(
                        available, component
                    ),
                    leave_one_out_contribution=(without_error - full_error)
                    if full_error is not None and without_error is not None
                    else None,
                    permutation_importance=_permutation_importance(
                        complete, coefficients, component
                    ),
                    confidence_interval_low=min(interval_values)
                    if interval_values
                    else None,
                    confidence_interval_high=max(interval_values)
                    if interval_values
                    else None,
                    sample_size=len(available),
                    completed_partition_count=len(partition_values),
                    partition_contributions=MappingProxyType(partition_values),
                    method_label=(
                        "standalone median split; deterministic ridge on realised R; "
                        "leave-one-out MSE; chronological-partition permutation"
                    ),
                )
            )
        return tuple(estimates)

    def _partition_coefficients(
        self, evidence: tuple[CompletedOutcomeEvidence, ...]
    ) -> dict[str, dict[AlphaComponent, Decimal]]:
        grouped: dict[str, list[CompletedOutcomeEvidence]] = defaultdict(list)
        for item in evidence:
            grouped[item.partition.value].append(item)
        return {
            partition: _ridge_coefficients(tuple(items))
            for partition, items in sorted(grouped.items())
            if len(items) >= 3
        }


def _ridge_coefficients(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    omitted: AlphaComponent | None = None,
) -> dict[AlphaComponent, Decimal]:
    components = tuple(item for item in AlphaComponent if item is not omitted)
    if len(evidence) < 3 or not components:
        return {}
    means = {
        component: _mean(item.score_for(component) or Decimal("0") for item in evidence)
        for component in components
    }
    response_mean = _mean(item.realized_r_multiple for item in evidence)
    matrix = [
        {
            component: (item.score_for(component) or Decimal("0")) - means[component]
            for component in components
        }
        for item in evidence
    ]
    response = [item.realized_r_multiple - response_mean for item in evidence]
    coefficients = {component: Decimal("0") for component in components}
    for _ in range(_ITERATIONS):
        for component in components:
            numerator = Decimal("0")
            denominator = _RIDGE_PENALTY
            for row_index, row in enumerate(matrix):
                residual = response[row_index] - sum(
                    row[other] * coefficients[other]
                    for other in components
                    if other is not component
                )
                numerator += row[component] * residual
                denominator += row[component] * row[component]
            coefficients[component] = (
                numerator / denominator if denominator else Decimal("0")
            )
    return coefficients


def _prediction_error(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    coefficients: dict[AlphaComponent, Decimal],
) -> Decimal | None:
    if len(evidence) < 3 or not coefficients:
        return None
    response_mean = _mean(item.realized_r_multiple for item in evidence)
    means = {
        component: _mean(item.score_for(component) or Decimal("0") for item in evidence)
        for component in coefficients
    }
    squared = []
    for item in evidence:
        prediction = response_mean + sum(
            coefficients[component]
            * ((item.score_for(component) or Decimal("0")) - means[component])
            for component in coefficients
        )
        squared.append((item.realized_r_multiple - prediction) ** 2)
    return _mean(squared)


def _standalone_difference(
    evidence: tuple[CompletedOutcomeEvidence, ...], component: AlphaComponent
) -> Decimal | None:
    if len(evidence) < 3:
        return None
    scores = sorted(item.score_for(component) or Decimal("0") for item in evidence)
    median = scores[len(scores) // 2]
    high = [
        item.realized_r_multiple
        for item in evidence
        if (item.score_for(component) or Decimal("0")) >= median
    ]
    low = [
        item.realized_r_multiple
        for item in evidence
        if (item.score_for(component) or Decimal("0")) < median
    ]
    if not high or not low:
        return None
    return _mean(high) - _mean(low)


def _conditional_contribution(
    evidence: tuple[CompletedOutcomeEvidence, ...], component: AlphaComponent
) -> Decimal | None:
    grouped: dict[tuple[str, str], list[CompletedOutcomeEvidence]] = defaultdict(list)
    for item in evidence:
        grouped[(item.setup_family, item.market_regime)].append(item)
    slopes = [
        slope
        for items in grouped.values()
        if len(items) >= 3
        and (slope := _univariate_slope(tuple(items), component)) is not None
    ]
    if not slopes:
        return None
    return max(slopes, key=lambda value: abs(value))


def _univariate_slope(
    evidence: tuple[CompletedOutcomeEvidence, ...], component: AlphaComponent
) -> Decimal | None:
    if len(evidence) < 3:
        return None
    x = [item.score_for(component) or Decimal("0") for item in evidence]
    y = [item.realized_r_multiple for item in evidence]
    x_mean = _mean(x)
    y_mean = _mean(y)
    denominator = sum(((value - x_mean) ** 2 for value in x), start=Decimal("0"))
    if denominator == Decimal("0"):
        return None
    numerator = sum(
        ((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y)),
        start=Decimal("0"),
    )
    return numerator / denominator


def _permutation_importance(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    coefficients: dict[AlphaComponent, Decimal],
    component: AlphaComponent,
) -> Decimal | None:
    baseline_error = _prediction_error(evidence, coefficients)
    if baseline_error is None or component not in coefficients or len(evidence) < 3:
        return None
    response_mean = _mean(item.realized_r_multiple for item in evidence)
    means = {
        current: _mean(item.score_for(current) or Decimal("0") for item in evidence)
        for current in coefficients
    }
    partition_indexes: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(evidence):
        partition_indexes[item.partition.value].append(index)
    permuted: dict[int, Decimal] = {}
    for indexes in partition_indexes.values():
        shifted = indexes[1:] + indexes[:1]
        for destination, source in zip(indexes, shifted, strict=True):
            permuted[destination] = evidence[source].score_for(component) or Decimal(
                "0"
            )
    squared = []
    for index, item in enumerate(evidence):
        prediction = response_mean
        for current, coefficient in coefficients.items():
            value = (
                permuted[index]
                if current is component
                else item.score_for(current) or Decimal("0")
            )
            prediction += coefficient * (value - means[current])
        squared.append((item.realized_r_multiple - prediction) ** 2)
    return _mean(squared) - baseline_error


def _mean(values: Iterable[Decimal]) -> Decimal:
    materialized = tuple(values)
    return (
        sum(materialized, start=Decimal("0")) / Decimal(len(materialized))
        if materialized
        else Decimal("0")
    )


__all__ = ["MarginalContributionEngine"]
