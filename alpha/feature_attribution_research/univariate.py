"""Deterministic univariate feature attribution without causal claims."""

from __future__ import annotations

import hashlib
import math
from decimal import Decimal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    DecileResult,
    EvidencePartition,
    FeatureDefinition,
    FeatureScalar,
    FeatureSnapshot,
    OutcomeRecord,
)
from alpha.feature_attribution_research.outcome_labels import outcome_value

DEFAULT_BINARY_OUTCOMES = (
    "TARGET_BEFORE_STOP",
    "POSITIVE_AFTER_COSTS_20D",
    "POSITIVE_AFTER_COSTS_60D",
    "POSITIVE_AFTER_COSTS_120D",
    "ACHIEVED_2R",
    "HIGH_QUALITY_WINNER",
)


class UnivariateAttributionEngine:
    def analyze(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        outcome_ids: tuple[str, ...] = DEFAULT_BINARY_OUTCOMES,
        minimum_support: int = 50,
        bootstrap_samples: int = 100,
    ) -> tuple[AttributionResult, ...]:
        if minimum_support < 2:
            raise ValueError("minimum support must be at least two")
        outcome_by_id = {item.onset_id: item for item in outcomes}
        cutoffs = _development_deciles(definitions, snapshots)
        results = []
        for definition in definitions:
            if not definition.point_in_time_safe:
                continue
            feature_rows = tuple(
                (
                    item.partition,
                    _numeric(item.value(definition.feature_id)),
                    outcome_by_id.get(item.onset_id),
                )
                for item in snapshots
            )
            for outcome_id in outcome_ids:
                horizon = _horizon(outcome_id)
                partition_rows: dict[
                    EvidencePartition, list[tuple[float, bool, Decimal | None]]
                ] = {partition: [] for partition in EvidencePartition}
                all_rows: list[tuple[float, bool, Decimal | None]] = []
                for row_partition, feature, outcome in feature_rows:
                    if feature is None or outcome is None:
                        continue
                    label = _binary(outcome_value(outcome, outcome_id))
                    if label is None:
                        continue
                    row = (feature, label, outcome.realized_r)
                    partition_rows[row_partition].append(row)
                    all_rows.append(row)
                for partition in (None, *EvidencePartition):
                    rows = tuple(
                        all_rows if partition is None else partition_rows[partition]
                    )
                    missing = sum(
                        item.partition is partition or partition is None
                        for item in snapshots
                    ) - len(rows)
                    results.append(
                        _result(
                            feature_id=definition.feature_id,
                            outcome_id=outcome_id,
                            partition=partition,
                            horizon=horizon,
                            rows=rows,
                            missing=max(0, missing),
                            cutoffs=cutoffs.get(definition.feature_id),
                            minimum_support=minimum_support,
                            bootstrap_samples=bootstrap_samples,
                        )
                    )
        return tuple(results)


def auc_score(values: NDArray[np.float64], labels: NDArray[np.bool_]) -> float | None:
    positives = int(np.sum(labels))
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ranks = pd.Series(values).rank(method="average").to_numpy(dtype=float)
    rank_sum = float(np.sum(ranks[labels]))
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _result(
    *,
    feature_id: str,
    outcome_id: str,
    partition: EvidencePartition | None,
    horizon: int | None,
    rows: tuple[tuple[float, bool, Decimal | None], ...],
    missing: int,
    cutoffs: NDArray[np.float64] | None,
    minimum_support: int,
    bootstrap_samples: int,
) -> AttributionResult:
    if len(rows) < minimum_support:
        return AttributionResult(
            feature_id=feature_id,
            outcome_id=outcome_id,
            partition=partition,
            horizon=horizon,
            sample_count=len(rows),
            missing_count=missing,
            winner_median=None,
            loser_median=None,
            median_difference=None,
            standardized_effect_size=None,
            rank_biserial_correlation=None,
            auc=None,
            monotonicity_score=None,
            bootstrap_low=None,
            bootstrap_high=None,
            direction=AttributionDirection.NO_EVIDENCE,
            deciles=(),
        )
    values = np.asarray([item[0] for item in rows], dtype=float)
    labels = np.asarray([item[1] for item in rows], dtype=bool)
    winners = values[labels]
    losers = values[~labels]
    auc = auc_score(values, labels)
    effect = _effect_size(winners, losers)
    deciles = _deciles(rows, cutoffs)
    monotonicity = _monotonicity(deciles)
    low, high = _bootstrap_auc(
        feature_id,
        outcome_id,
        partition,
        values,
        labels,
        samples=bootstrap_samples,
    )
    return AttributionResult(
        feature_id=feature_id,
        outcome_id=outcome_id,
        partition=partition,
        horizon=horizon,
        sample_count=len(rows),
        missing_count=missing,
        winner_median=_decimal(float(np.median(winners))) if winners.size else None,
        loser_median=_decimal(float(np.median(losers))) if losers.size else None,
        median_difference=(
            None
            if not winners.size or not losers.size
            else _decimal(float(np.median(winners) - np.median(losers)))
        ),
        standardized_effect_size=_optional_decimal(effect),
        rank_biserial_correlation=(None if auc is None else _decimal(2 * auc - 1)),
        auc=_optional_decimal(auc),
        monotonicity_score=_optional_decimal(monotonicity),
        bootstrap_low=_optional_decimal(low),
        bootstrap_high=_optional_decimal(high),
        direction=_direction(auc, monotonicity, low, high, deciles),
        deciles=deciles,
    )


def _development_deciles(
    definitions: tuple[FeatureDefinition, ...],
    snapshots: tuple[FeatureSnapshot, ...],
) -> dict[str, NDArray[np.float64]]:
    result = {}
    development = tuple(
        item for item in snapshots if item.partition is EvidencePartition.DEVELOPMENT
    )
    for definition in definitions:
        values = np.asarray(
            [
                value
                for item in development
                if (value := _numeric(item.value(definition.feature_id))) is not None
            ],
            dtype=float,
        )
        if values.size >= 10:
            result[definition.feature_id] = np.unique(
                np.quantile(values, np.arange(0.1, 1.0, 0.1))
            )
    return result


def _deciles(
    rows: tuple[tuple[float, bool, Decimal | None], ...],
    cutoffs: NDArray[np.float64] | None,
) -> tuple[DecileResult, ...]:
    if cutoffs is None or cutoffs.size == 0:
        return ()
    buckets: dict[int, list[tuple[bool, Decimal | None]]] = {
        item: [] for item in range(1, 11)
    }
    for value, label, realized_r in rows:
        bucket = min(10, int(np.searchsorted(cutoffs, value, side="right")) + 1)
        buckets[bucket].append((label, realized_r))
    result = []
    for bucket, values in buckets.items():
        winner_rate = (
            None if not values else sum(item[0] for item in values) / len(values)
        )
        expectancy_values = [float(item[1]) for item in values if item[1] is not None]
        result.append(
            DecileResult(
                decile=bucket,
                sample_count=len(values),
                winner_rate=_optional_decimal(winner_rate),
                precision=_optional_decimal(winner_rate),
                expectancy=(
                    None
                    if not expectancy_values
                    else _decimal(float(np.mean(expectancy_values)))
                ),
            )
        )
    return tuple(result)


def _monotonicity(deciles: tuple[DecileResult, ...]) -> float | None:
    rows = tuple(
        (item.decile, float(item.winner_rate))
        for item in deciles
        if item.winner_rate is not None and item.sample_count > 0
    )
    if len(rows) < 3:
        return None
    first = np.asarray([item[0] for item in rows], dtype=float)
    second = np.asarray([item[1] for item in rows], dtype=float)
    if np.std(second) == 0:
        return 0.0
    return float(np.corrcoef(first, second)[0, 1])


def _effect_size(
    winners: NDArray[np.float64], losers: NDArray[np.float64]
) -> float | None:
    if winners.size < 2 or losers.size < 2:
        return None
    denominator = math.sqrt(
        (
            (winners.size - 1) * np.var(winners, ddof=1)
            + (losers.size - 1) * np.var(losers, ddof=1)
        )
        / (winners.size + losers.size - 2)
    )
    return (
        None
        if denominator == 0
        else float((np.mean(winners) - np.mean(losers)) / denominator)
    )


def _bootstrap_auc(
    feature_id: str,
    outcome_id: str,
    partition: EvidencePartition | None,
    values: NDArray[np.float64],
    labels: NDArray[np.bool_],
    *,
    samples: int,
) -> tuple[float | None, float | None]:
    if samples < 1:
        return None, None
    seed_text = f"{feature_id}|{outcome_id}|{partition or 'ALL'}"
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    sample_size = min(len(values), 2_000)
    estimates = []
    for _ in range(samples):
        indices = rng.integers(0, len(values), size=sample_size)
        estimate = auc_score(values[indices], labels[indices])
        if estimate is not None:
            estimates.append(estimate)
    if len(estimates) < max(5, samples // 10):
        return None, None
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def _direction(
    auc: float | None,
    monotonicity: float | None,
    low: float | None,
    high: float | None,
    deciles: tuple[DecileResult, ...],
) -> AttributionDirection:
    if auc is None or low is None or high is None or low <= 0.5 <= high:
        return AttributionDirection.NO_EVIDENCE
    rates = [
        float(item.winner_rate) for item in deciles if item.winner_rate is not None
    ]
    if (
        monotonicity is not None
        and abs(monotonicity) < 0.35
        and rates
        and max(rates) - min(rates) >= 0.10
    ):
        return AttributionDirection.NON_MONOTONIC
    if auc >= 0.55:
        return AttributionDirection.POSITIVE
    if auc <= 0.45:
        return AttributionDirection.NEGATIVE
    return AttributionDirection.NO_EVIDENCE


def _binary(value: bool | Decimal | None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value > 0
    return None


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _horizon(outcome_id: str) -> int | None:
    for value in (20, 60, 120):
        if f"{value}D" in outcome_id:
            return value
    return (
        120
        if outcome_id in {"TARGET_BEFORE_STOP", "ACHIEVED_2R", "HIGH_QUALITY_WINNER"}
        else None
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None or not math.isfinite(value) else _decimal(value)


__all__ = ["DEFAULT_BINARY_OUTCOMES", "UnivariateAttributionEngine", "auc_score"]
