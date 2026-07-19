"""Multi-axis feature stability and information-decay analysis."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal

import numpy as np

from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    ConditionalAttributionResult,
    EvidencePartition,
    FeatureDefinition,
    FeatureQualityFlag,
    FeatureQualityRecord,
    FeatureScalar,
    FeatureSnapshot,
    FeatureStabilityScore,
    InformationDecayResult,
    OutcomeRecord,
    StabilityClassification,
)
from alpha.feature_attribution_research.univariate import auc_score


class FeatureStabilityEngine:
    def analyze(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        univariate: tuple[AttributionResult, ...],
        conditional: tuple[ConditionalAttributionResult, ...],
        quality: tuple[FeatureQualityRecord, ...],
        minimum_support: int = 50,
    ) -> tuple[FeatureStabilityScore, ...]:
        outcomes_by_id = {item.onset_id: item for item in outcomes}
        quality_by_id = {item.feature_id: item for item in quality}
        partition_population = {
            partition: sum(item.partition is partition for item in snapshots)
            for partition in EvidencePartition
        }
        results = []
        for definition in definitions:
            feature_id = definition.feature_id
            partition_rows = {
                item.partition: item
                for item in univariate
                if item.feature_id == feature_id
                and item.outcome_id == "TARGET_BEFORE_STOP"
                and item.partition is not None
            }
            signs = tuple(
                _direction_sign(partition_rows.get(partition))
                for partition in EvidencePartition
            )
            supported_signs = tuple(item for item in signs if item != 0)
            direction_stability = (
                None
                if not supported_signs
                else Decimal(max(supported_signs.count(1), supported_signs.count(-1)))
                / Decimal(len(supported_signs))
            )
            support_rates = tuple(
                Decimal(partition_rows[item].sample_count)
                / Decimal(partition_population[item])
                for item in EvidencePartition
                if item in partition_rows and partition_population[item] > 0
            )
            support_stability = (
                None
                if not support_rates or max(support_rates) == 0
                else min(support_rates) / max(support_rates)
            )
            era_stability = _era_stability(
                feature_id, snapshots, outcomes_by_id, minimum_support
            )
            liquidity_stability = _conditional_stability(
                feature_id, conditional, "liquidity_bucket"
            )
            unavailable = ["regime_stability", "sector_stability"]
            available_scores = tuple(
                item
                for item in (
                    direction_stability,
                    support_stability,
                    era_stability,
                    liquidity_stability,
                )
                if item is not None
            )
            overall = (
                None
                if not available_scores
                else sum(available_scores, Decimal("0"))
                / Decimal(len(available_scores))
            )
            results.append(
                FeatureStabilityScore(
                    feature_id=feature_id,
                    direction_stability=direction_stability,
                    support_stability=support_stability,
                    era_stability=era_stability,
                    regime_stability=None,
                    sector_stability=None,
                    liquidity_stability=liquidity_stability,
                    overall_stability=overall,
                    classification=_classification(
                        definition.point_in_time_safe,
                        quality_by_id.get(feature_id),
                        partition_rows,
                        signs,
                        overall,
                        minimum_support,
                    ),
                    unavailable_dimensions=tuple(unavailable),
                )
            )
        return tuple(results)


class InformationDecayEngine:
    def analyze(
        self, univariate: tuple[AttributionResult, ...]
    ) -> tuple[InformationDecayResult, ...]:
        rows = []
        for item in univariate:
            if item.partition is not None:
                continue
            horizon = _positive_horizon(item.outcome_id)
            if horizon is None:
                continue
            rows.append(
                InformationDecayResult(
                    feature_id=item.feature_id,
                    horizon=horizon,
                    outcome_id=item.outcome_id,
                    sample_count=item.sample_count,
                    auc=item.auc,
                    effect=item.standardized_effect_size,
                    direction=item.direction,
                )
            )
        return tuple(rows)


def _era_stability(
    feature_id: str,
    snapshots: tuple[FeatureSnapshot, ...],
    outcomes: Mapping[str, OutcomeRecord],
    minimum_support: int,
) -> Decimal | None:
    grouped: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for snapshot in snapshots:
        value = _numeric(snapshot.value(feature_id))
        outcome = outcomes.get(snapshot.onset_id)
        if value is None or outcome is None or outcome.target_before_stop is None:
            continue
        grouped[snapshot.onset_date.year].append((value, outcome.target_before_stop))
    signs = []
    for rows in grouped.values():
        if len(rows) < minimum_support:
            continue
        auc = auc_score(
            np.asarray([item[0] for item in rows], dtype=float),
            np.asarray([item[1] for item in rows], dtype=bool),
        )
        sign = _auc_sign(auc)
        if sign != 0:
            signs.append(sign)
    if not signs:
        return None
    return Decimal(max(signs.count(1), signs.count(-1))) / Decimal(len(signs))


def _conditional_stability(
    feature_id: str,
    values: tuple[ConditionalAttributionResult, ...],
    context_name: str,
) -> Decimal | None:
    signs = [
        _attribution_sign(item.direction)
        for item in values
        if item.feature_id == feature_id
        and item.context_name == context_name
        and item.auc is not None
    ]
    signs = [item for item in signs if item != 0]
    if not signs:
        return None
    return Decimal(max(signs.count(1), signs.count(-1))) / Decimal(len(signs))


def _classification(
    point_in_time_safe: bool,
    quality: FeatureQualityRecord | None,
    partitions: Mapping[EvidencePartition, AttributionResult],
    signs: tuple[int, ...],
    overall: Decimal | None,
    minimum_support: int,
) -> StabilityClassification:
    if not point_in_time_safe or quality is None:
        return StabilityClassification.DATA_QUALITY_BLOCKED
    blocked = {
        FeatureQualityFlag.ZERO_VARIANCE,
        FeatureQualityFlag.DATA_NOT_POINT_IN_TIME,
    }
    if blocked.intersection(quality.flags):
        return StabilityClassification.DATA_QUALITY_BLOCKED
    if any(
        partition not in partitions
        or partitions[partition].sample_count < minimum_support
        or partitions[partition].auc is None
        for partition in EvidencePartition
    ):
        return StabilityClassification.INSUFFICIENT_EVIDENCE
    development, validation, holdout = signs
    if development != 0 and holdout == -development:
        return StabilityClassification.HOLDOUT_FAILURE
    if development != 0 and validation == 0 and holdout == 0:
        return StabilityClassification.DEVELOPMENT_ONLY
    if len(set(item for item in signs if item != 0)) > 1:
        return StabilityClassification.CONTEXT_DEPENDENT
    if overall is None or overall < Decimal("0.70"):
        return StabilityClassification.CONTEXT_DEPENDENT
    if development == validation == holdout == 1:
        return StabilityClassification.STABLE_POSITIVE
    if development == validation == holdout == -1:
        return StabilityClassification.STABLE_NEGATIVE
    return StabilityClassification.INSUFFICIENT_EVIDENCE


def _direction_sign(value: AttributionResult | None) -> int:
    return 0 if value is None else _attribution_sign(value.direction)


def _attribution_sign(value: AttributionDirection) -> int:
    if value is AttributionDirection.POSITIVE:
        return 1
    if value is AttributionDirection.NEGATIVE:
        return -1
    return 0


def _auc_sign(value: float | None) -> int:
    if value is None or abs(value - 0.5) < 0.02:
        return 0
    return 1 if value > 0.5 else -1


def _positive_horizon(outcome_id: str) -> int | None:
    for horizon in (20, 60, 120):
        if outcome_id == f"POSITIVE_AFTER_COSTS_{horizon}D":
            return horizon
    return None


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


__all__ = ["FeatureStabilityEngine", "InformationDecayEngine"]
