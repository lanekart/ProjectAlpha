"""Chronological orthogonal-edge probes using frozen development scorecards."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from alpha.feature_attribution_research.models import (
    OUTCOME_DEFINITION_COUPLED_FEATURES,
    AttributionResult,
    EvidencePartition,
    FeatureDefinition,
    FeatureScalar,
    FeatureSnapshot,
    OrthogonalEdgeResult,
    OutcomeRecord,
    RedundancyClassification,
    RedundancyResult,
)
from alpha.feature_attribution_research.univariate import auc_score


@dataclass(frozen=True, slots=True)
class _Scorecard:
    cutoffs: tuple[float, ...]
    rates: tuple[float, ...]
    fallback: float

    def score(self, value: float | None) -> float:
        if value is None:
            return self.fallback
        bucket = min(
            len(self.rates) - 1,
            int(np.searchsorted(self.cutoffs, value, side="right")),
        )
        return self.rates[bucket]


class OrthogonalEdgeAudit:
    """Compare frozen monotonic scorecards without producing deployable models."""

    def analyze(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        univariate: tuple[AttributionResult, ...],
        redundancy: tuple[RedundancyResult, ...],
        minimum_support: int = 100,
    ) -> tuple[OrthogonalEdgeResult, ...]:
        labels = {
            item.onset_id: item.target_before_stop
            for item in outcomes
            if item.target_before_stop is not None
        }
        usable = tuple(
            item.feature_id
            for item in definitions
            if item.point_in_time_safe
            and item.feature_id not in OUTCOME_DEFINITION_COUPLED_FEATURES
            and _available_count(snapshots, item.feature_id) >= minimum_support
        )
        baseline_features = _baseline_features(
            univariate, usable, redundancy=redundancy, limit=3
        )
        maybe_baseline_cards = {
            feature: _fit_scorecard(feature, snapshots, labels)
            for feature in baseline_features
        }
        baseline_cards = {
            feature: card
            for feature, card in maybe_baseline_cards.items()
            if card is not None
        }
        baseline_scores = _scores(snapshots, baseline_cards)
        baseline_metrics = _partition_metrics(snapshots, labels, baseline_scores)
        results = []
        for feature in usable:
            card = _fit_scorecard(feature, snapshots, labels)
            if card is None:
                continue
            comparator_cards = {
                feature_id: baseline_card
                for feature_id, baseline_card in baseline_cards.items()
                if feature_id != feature
            }
            comparator_metrics = (
                baseline_metrics
                if feature not in baseline_cards
                else _partition_metrics(
                    snapshots,
                    labels,
                    _scores(snapshots, comparator_cards),
                )
            )
            cards = dict(comparator_cards)
            cards[feature] = card
            scores = _scores(snapshots, cards)
            metrics = _partition_metrics(snapshots, labels, scores)
            holdout_auc = metrics[EvidencePartition.HOLDOUT][0]
            baseline_holdout_auc = comparator_metrics[EvidencePartition.HOLDOUT][0]
            holdout_brier = metrics[EvidencePartition.HOLDOUT][1]
            baseline_holdout_brier = comparator_metrics[EvidencePartition.HOLDOUT][1]
            signs = tuple(
                _sign(metrics[partition][0]) for partition in EvidencePartition
            )
            results.append(
                OrthogonalEdgeResult(
                    feature_id=feature,
                    model_name="development_frozen_monotonic_bin_scorecard",
                    development_auc=_decimal_metric(
                        metrics[EvidencePartition.DEVELOPMENT][0]
                    ),
                    validation_auc=_decimal_metric(
                        metrics[EvidencePartition.VALIDATION][0]
                    ),
                    holdout_auc=_decimal_metric(holdout_auc),
                    development_brier=_decimal_metric(
                        metrics[EvidencePartition.DEVELOPMENT][1]
                    ),
                    validation_brier=_decimal_metric(
                        metrics[EvidencePartition.VALIDATION][1]
                    ),
                    holdout_brier=_decimal_metric(holdout_brier),
                    incremental_auc=_decimal_metric(
                        _difference(holdout_auc, baseline_holdout_auc)
                    ),
                    incremental_brier_improvement=_decimal_metric(
                        _difference(baseline_holdout_brier, holdout_brier)
                    ),
                    calibration_slope=_decimal_metric(
                        metrics[EvidencePartition.HOLDOUT][2]
                    ),
                    feature_sign_stability=(0 not in signs and len(set(signs)) == 1),
                    sample_count=sum(item.onset_id in labels for item in snapshots),
                )
            )
        for model_name, feature_set in (
            (
                "canonical_component_model",
                tuple(
                    item
                    for item in usable
                    if item.endswith("_component") or item == "canonical_total_score"
                ),
            ),
            (
                "raw_feature_model",
                tuple(item for item in baseline_features if "component" not in item),
            ),
        ):
            model_cards = {
                feature: card
                for feature in feature_set
                if (card := _fit_scorecard(feature, snapshots, labels)) is not None
            }
            if not model_cards:
                continue
            metrics = _partition_metrics(
                snapshots, labels, _scores(snapshots, model_cards)
            )
            results.append(
                OrthogonalEdgeResult(
                    feature_id=f"__{model_name}__",
                    model_name=model_name,
                    development_auc=_decimal_metric(
                        metrics[EvidencePartition.DEVELOPMENT][0]
                    ),
                    validation_auc=_decimal_metric(
                        metrics[EvidencePartition.VALIDATION][0]
                    ),
                    holdout_auc=_decimal_metric(metrics[EvidencePartition.HOLDOUT][0]),
                    development_brier=_decimal_metric(
                        metrics[EvidencePartition.DEVELOPMENT][1]
                    ),
                    validation_brier=_decimal_metric(
                        metrics[EvidencePartition.VALIDATION][1]
                    ),
                    holdout_brier=_decimal_metric(
                        metrics[EvidencePartition.HOLDOUT][1]
                    ),
                    incremental_auc=None,
                    incremental_brier_improvement=None,
                    calibration_slope=_decimal_metric(
                        metrics[EvidencePartition.HOLDOUT][2]
                    ),
                    feature_sign_stability=True,
                    sample_count=sum(item.onset_id in labels for item in snapshots),
                )
            )
        return tuple(results)


def _fit_scorecard(
    feature_id: str,
    snapshots: tuple[FeatureSnapshot, ...],
    labels: Mapping[str, bool],
) -> _Scorecard | None:
    rows = tuple(
        (value, labels[item.onset_id])
        for item in snapshots
        if item.partition is EvidencePartition.DEVELOPMENT
        and item.onset_id in labels
        and (value := _numeric(item.value(feature_id))) is not None
    )
    if len(rows) < 100:
        return None
    values = np.asarray([item[0] for item in rows], dtype=float)
    outcomes = np.asarray([item[1] for item in rows], dtype=bool)
    cutoffs = tuple(
        float(item) for item in np.unique(np.quantile(values, np.arange(0.1, 1.0, 0.1)))
    )
    fallback = float(np.mean(outcomes))
    bucket_count = len(cutoffs) + 1
    rates = []
    for bucket in range(bucket_count):
        mask = np.searchsorted(cutoffs, values, side="right") == bucket
        successes = int(np.sum(outcomes[mask]))
        count = int(np.sum(mask))
        rates.append((successes + 1) / (count + 2))
    return _Scorecard(cutoffs=cutoffs, rates=tuple(rates), fallback=fallback)


def _scores(
    snapshots: tuple[FeatureSnapshot, ...],
    cards: Mapping[str, _Scorecard],
) -> dict[str, float]:
    return {
        item.onset_id: float(
            np.mean(
                [
                    card.score(_numeric(item.value(feature)))
                    for feature, card in cards.items()
                ]
            )
        )
        for item in snapshots
        if cards
    }


def _partition_metrics(
    snapshots: tuple[FeatureSnapshot, ...],
    labels: Mapping[str, bool],
    scores: Mapping[str, float],
) -> dict[EvidencePartition, tuple[float | None, float | None, float | None]]:
    result: dict[
        EvidencePartition, tuple[float | None, float | None, float | None]
    ] = {}
    for partition in EvidencePartition:
        rows = tuple(
            (scores[item.onset_id], labels[item.onset_id])
            for item in snapshots
            if item.partition is partition
            and item.onset_id in labels
            and item.onset_id in scores
        )
        if not rows:
            result[partition] = (None, None, None)
            continue
        predictions = np.asarray([item[0] for item in rows], dtype=float)
        outcomes = np.asarray([item[1] for item in rows], dtype=bool)
        auc = auc_score(predictions, outcomes)
        brier = float(np.mean((predictions - outcomes.astype(float)) ** 2))
        result[partition] = (auc, brier, _calibration_slope(predictions, outcomes))
    return result


def _calibration_slope(
    predictions: NDArray[np.float64],
    outcomes: NDArray[np.bool_],
) -> float | None:
    if len(predictions) < 20 or np.std(predictions) == 0:
        return None
    clipped = np.clip(predictions, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped))
    if np.std(logits) == 0:
        return None
    return float(
        np.cov(logits, outcomes.astype(float), ddof=1)[0, 1] / np.var(logits, ddof=1)
    )


def _baseline_features(
    univariate: tuple[AttributionResult, ...],
    usable: tuple[str, ...],
    *,
    redundancy: tuple[RedundancyResult, ...],
    limit: int,
) -> tuple[str, ...]:
    rows = tuple(
        item
        for item in univariate
        if item.feature_id in usable
        and item.feature_id not in OUTCOME_DEFINITION_COUPLED_FEATURES
        and item.outcome_id == "TARGET_BEFORE_STOP"
        and item.partition is EvidencePartition.DEVELOPMENT
        and item.auc is not None
        and "component" not in item.feature_id
    )
    ordered = sorted(
        rows,
        key=lambda item: (
            _auc_distance(item),
            item.sample_count,
            item.feature_id,
        ),
        reverse=True,
    )
    redundant_pairs = {
        frozenset((item.feature_a, item.feature_b))
        for item in redundancy
        if item.classification
        in {
            RedundancyClassification.HIGHLY_REDUNDANT,
            RedundancyClassification.SAME_SOURCE_DUPLICATE,
        }
    }
    selected: list[str] = []
    for item in ordered:
        if any(
            frozenset((item.feature_id, existing)) in redundant_pairs
            for existing in selected
        ):
            continue
        selected.append(item.feature_id)
        if len(selected) == limit:
            break
    return tuple(selected)


def _auc_distance(item: AttributionResult) -> Decimal:
    return Decimal("0") if item.auc is None else abs(item.auc - Decimal("0.5"))


def _available_count(snapshots: tuple[FeatureSnapshot, ...], feature_id: str) -> int:
    return sum(_numeric(item.value(feature_id)) is not None for item in snapshots)


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _sign(value: float | None) -> int:
    if value is None or abs(value - 0.5) < 0.01:
        return 0
    return 1 if value > 0.5 else -1


def _difference(first: float | None, second: float | None) -> float | None:
    return None if first is None or second is None else first - second


def _decimal_metric(value: float | None) -> Decimal | None:
    return None if value is None or not math.isfinite(value) else Decimal(str(value))


__all__ = ["OrthogonalEdgeAudit"]
