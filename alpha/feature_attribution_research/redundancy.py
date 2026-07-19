"""Correlation, information overlap, and same-source lineage audit."""

from __future__ import annotations

import math
from decimal import Decimal
from itertools import combinations

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from alpha.feature_attribution_research.models import (
    FeatureDefinition,
    FeatureScalar,
    FeatureSnapshot,
    OutcomeRecord,
    RedundancyClassification,
    RedundancyResult,
)
from alpha.feature_attribution_research.univariate import auc_score


class FeatureRedundancyEngine:
    def analyze(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        minimum_support: int = 100,
    ) -> tuple[RedundancyResult, ...]:
        by_id = {item.feature_id: item for item in definitions}
        outcomes_by_id = {item.onset_id: item.target_before_stop for item in outcomes}
        labelled = np.asarray(
            [outcomes_by_id.get(item.onset_id) is not None for item in snapshots],
            dtype=bool,
        )
        labels = np.asarray(
            [bool(outcomes_by_id.get(item.onset_id)) for item in snapshots],
            dtype=bool,
        )
        values_by_feature = {
            item.feature_id: np.asarray(
                [
                    value
                    if (value := _numeric(row.value(item.feature_id))) is not None
                    else np.nan
                    for row in snapshots
                ],
                dtype=float,
            )
            for item in definitions
            if item.point_in_time_safe
        }
        available = tuple(
            item.feature_id
            for item in definitions
            if item.point_in_time_safe
            and int(np.sum(np.isfinite(values_by_feature[item.feature_id])))
            >= minimum_support
        )
        results = []
        for first, second in combinations(available, 2):
            first_values = values_by_feature[first]
            second_values = values_by_feature[second]
            mask = labelled & np.isfinite(first_values) & np.isfinite(second_values)
            sample_count = int(np.sum(mask))
            if sample_count < minimum_support:
                continue
            values_a = first_values[mask]
            values_b = second_values[mask]
            paired_labels = labels[mask]
            pearson = _correlation(values_a, values_b)
            spearman = _correlation(
                np.asarray(
                    pd.Series(values_a).rank(method="average").to_numpy(dtype=float),
                    dtype=np.float64,
                ),
                np.asarray(
                    pd.Series(values_b).rank(method="average").to_numpy(dtype=float),
                    dtype=np.float64,
                ),
            )
            mutual = _normalized_mutual_information(values_a, values_b)
            lineage = _jaccard(
                by_id[first].source_lineage, by_id[second].source_lineage
            )
            incremental = _incremental_auc(values_a, values_b, paired_labels)
            results.append(
                RedundancyResult(
                    feature_a=first,
                    feature_b=second,
                    sample_count=sample_count,
                    pearson=_optional_decimal(pearson),
                    spearman=_optional_decimal(spearman),
                    mutual_information=_optional_decimal(mutual),
                    source_lineage_jaccard=Decimal(str(lineage)),
                    incremental_auc=_optional_decimal(incremental),
                    classification=_classification(pearson, spearman, mutual, lineage),
                )
            )
        return tuple(results)


def clustered_feature_groups(
    results: tuple[RedundancyResult, ...],
) -> tuple[tuple[str, ...], ...]:
    graph: dict[str, set[str]] = {}
    for item in results:
        if item.classification not in {
            RedundancyClassification.HIGHLY_REDUNDANT,
            RedundancyClassification.SAME_SOURCE_DUPLICATE,
        }:
            continue
        graph.setdefault(item.feature_a, set()).add(item.feature_b)
        graph.setdefault(item.feature_b, set()).add(item.feature_a)
    groups = []
    visited: set[str] = set()
    for feature in sorted(graph):
        if feature in visited:
            continue
        pending = [feature]
        group: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            group.add(current)
            pending.extend(sorted(graph.get(current, ()), reverse=True))
        groups.append(tuple(sorted(group)))
    return tuple(groups)


def _normalized_mutual_information(
    first: NDArray[np.float64], second: NDArray[np.float64]
) -> float | None:
    if len(first) < 10:
        return None
    bins_a = _bins(first)
    bins_b = _bins(second)
    table = np.zeros((10, 10), dtype=float)
    for item_a, item_b in zip(bins_a, bins_b, strict=True):
        table[item_a, item_b] += 1
    total = float(np.sum(table))
    if total <= 0:
        return None
    joint = table / total
    marginal_a = np.sum(joint, axis=1)
    marginal_b = np.sum(joint, axis=0)
    mutual = 0.0
    for left in range(10):
        for right in range(10):
            probability = joint[left, right]
            if probability > 0 and marginal_a[left] > 0 and marginal_b[right] > 0:
                mutual += probability * math.log(
                    probability / (marginal_a[left] * marginal_b[right])
                )
    entropy_a = -sum(item * math.log(item) for item in marginal_a if item > 0)
    entropy_b = -sum(item * math.log(item) for item in marginal_b if item > 0)
    denominator = max(entropy_a, entropy_b)
    return None if denominator <= 0 else mutual / denominator


def _bins(values: NDArray[np.float64]) -> NDArray[np.int64]:
    cutoffs = np.unique(np.quantile(values, np.arange(0.1, 1.0, 0.1)))
    return np.minimum(9, np.searchsorted(cutoffs, values, side="right"))


def _incremental_auc(
    first: NDArray[np.float64],
    second: NDArray[np.float64],
    labels: NDArray[np.bool_],
) -> float | None:
    first_rank = np.asarray(
        pd.Series(first).rank(pct=True).to_numpy(dtype=float), dtype=np.float64
    )
    second_rank = np.asarray(
        pd.Series(second).rank(pct=True).to_numpy(dtype=float), dtype=np.float64
    )
    auc_a = auc_score(first_rank, labels)
    auc_b = auc_score(second_rank, labels)
    if auc_a is None or auc_b is None:
        return None
    if auc_a < 0.5:
        first_rank = 1 - first_rank
        auc_a = 1 - auc_a
    if auc_b < 0.5:
        second_rank = 1 - second_rank
        auc_b = 1 - auc_b
    combined = auc_score((first_rank + second_rank) / 2, labels)
    return None if combined is None else combined - max(auc_a, auc_b)


def _classification(
    pearson: float | None,
    spearman: float | None,
    mutual: float | None,
    lineage: float,
) -> RedundancyClassification:
    correlations = [abs(item) for item in (pearson, spearman) if item is not None]
    strongest = max(correlations, default=0.0)
    if lineage == 1.0 and strongest >= 0.98:
        return RedundancyClassification.SAME_SOURCE_DUPLICATE
    if strongest >= 0.90 or (mutual is not None and mutual >= 0.75):
        return RedundancyClassification.HIGHLY_REDUNDANT
    if strongest >= 0.70 or lineage >= 0.50:
        return RedundancyClassification.PARTIALLY_REDUNDANT
    return RedundancyClassification.ORTHOGONAL


def _correlation(
    first: NDArray[np.float64], second: NDArray[np.float64]
) -> float | None:
    if len(first) < 3 or np.std(first) == 0 or np.std(second) == 0:
        return None
    return float(np.corrcoef(first, second)[0, 1])


def _jaccard(first: tuple[str, ...], second: tuple[str, ...]) -> float:
    left, right = set(first), set(second)
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None or not math.isfinite(value) else Decimal(str(value))


__all__ = ["FeatureRedundancyEngine", "clustered_feature_groups"]
