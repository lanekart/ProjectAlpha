"""Deterministic feature-level case studies for mandatory symbols."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from alpha.feature_attribution_research.models import (
    OUTCOME_DEFINITION_COUPLED_FEATURES,
    AttributionDirection,
    AttributionResult,
    CaseStudy,
    EvidencePartition,
    FeatureDefinition,
    FeatureLeakageRecord,
    FeatureRanking,
    FeatureScalar,
    FeatureSnapshot,
    FeatureStabilityScore,
    OutcomeRecord,
    ResearchConclusion,
    ResearchPopulationRecord,
    StabilityClassification,
)

MANDATORY_SYMBOLS = (
    "KALYANKJIL",
    "PCJEWELLER",
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "LT",
    "TATASTEEL",
)


class FeatureCaseStudyEngine:
    def build(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        population: tuple[ResearchPopulationRecord, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        univariate: tuple[AttributionResult, ...],
        stability: tuple[FeatureStabilityScore, ...],
        leakage: tuple[FeatureLeakageRecord, ...],
        rankings: tuple[FeatureRanking, ...],
        symbols: tuple[str, ...] = MANDATORY_SYMBOLS,
    ) -> tuple[CaseStudy, ...]:
        population_by_id = {item.onset_id: item for item in population}
        outcomes_by_id = {item.onset_id: item for item in outcomes}
        stability_by_id = {item.feature_id: item for item in stability}
        outcome_coupled = {
            item.feature_id for item in leakage if item.outcome_definition_coupled
        }
        redundant = {
            item.feature_id
            for item in rankings
            if item.ranking_name == "operational_availability"
            and item.conclusion is ResearchConclusion.FEATURE_IS_REDUNDANT
        }
        excluded = (
            outcome_coupled | redundant | set(OUTCOME_DEFINITION_COUPLED_FEATURES)
        )
        attribution = {
            item.feature_id: item
            for item in univariate
            if item.outcome_id == "TARGET_BEFORE_STOP" and item.partition is None
        }
        distributions = _development_distributions(definitions, snapshots)
        rows = []
        for symbol in symbols:
            candidates = tuple(
                item
                for item in snapshots
                if item.symbol == symbol and item.onset_id in outcomes_by_id
            )
            selected = max(
                candidates,
                key=lambda item: (
                    outcomes_by_id[item.onset_id].target_before_stop is not None,
                    item.onset_date,
                    item.onset_id,
                ),
                default=None,
            )
            if selected is None:
                rows.append(_unavailable(symbol))
                continue
            population_row = population_by_id[selected.onset_id]
            outcome = outcomes_by_id[selected.onset_id]
            percentiles = _percentiles(selected, distributions)
            positive, negative = _evidence_lists(
                percentiles, attribution, exclude=excluded
            )
            missing_groups = tuple(
                sorted(
                    {
                        definition.feature_group.value
                        for definition in definitions
                        if selected.value(definition.feature_id) is None
                    }
                )
            )
            stable_features = tuple(
                dict.fromkeys(
                    feature_id
                    for feature_id, _ in (*positive, *negative)
                    if stability_by_id.get(feature_id) is not None
                    and stability_by_id[feature_id].classification
                    in {
                        StabilityClassification.STABLE_POSITIVE,
                        StabilityClassification.STABLE_NEGATIVE,
                    }
                )
            )
            differentiates = bool(stable_features)
            rows.append(
                CaseStudy(
                    symbol=symbol,
                    onset_id=selected.onset_id,
                    onset_date=selected.onset_date,
                    outcome=_outcome_text(outcome),
                    canonical_result=population_row.candidate_status,
                    top_positive_features=tuple(positive[:5]),
                    top_negative_features=tuple(negative[:5]),
                    population_percentiles=tuple(percentiles[:10]),
                    missing_feature_groups=missing_groups,
                    differentiation_available_point_in_time=differentiates,
                    explanation=_explanation(
                        symbol,
                        selected,
                        outcome,
                        stable_features,
                        missing_groups,
                    ),
                )
            )
        return tuple(rows)


def _development_distributions(
    definitions: tuple[FeatureDefinition, ...],
    snapshots: tuple[FeatureSnapshot, ...],
) -> dict[str, NDArray[np.float64]]:
    result = {}
    for definition in definitions:
        values = np.asarray(
            [
                value
                for item in snapshots
                if item.partition is EvidencePartition.DEVELOPMENT
                and (value := _numeric(item.value(definition.feature_id))) is not None
            ],
            dtype=float,
        )
        if values.size:
            result[definition.feature_id] = np.sort(values)
    return result


def _percentiles(
    snapshot: FeatureSnapshot,
    distributions: Mapping[str, NDArray[np.float64]],
) -> list[tuple[str, Decimal]]:
    rows = []
    for feature_id, distribution in distributions.items():
        value = _numeric(snapshot.value(feature_id))
        if value is None or distribution.size == 0:
            continue
        percentile = (
            np.searchsorted(distribution, value, side="right") / distribution.size
        )
        rows.append((feature_id, Decimal(str(percentile))))
    return sorted(
        rows, key=lambda item: (abs(item[1] - Decimal("0.5")), item[0]), reverse=True
    )


def _evidence_lists(
    percentiles: list[tuple[str, Decimal]],
    attribution: Mapping[str, AttributionResult],
    *,
    exclude: set[str],
) -> tuple[list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
    positive = []
    negative = []
    for feature_id, percentile in percentiles:
        if feature_id in exclude:
            continue
        row = attribution.get(feature_id)
        if row is None or row.direction not in {
            AttributionDirection.POSITIVE,
            AttributionDirection.NEGATIVE,
        }:
            continue
        support = (
            percentile
            if row.direction is AttributionDirection.POSITIVE
            else Decimal("1") - percentile
        )
        opposition = Decimal("1") - support
        positive.append((feature_id, support))
        negative.append((feature_id, opposition))
    positive.sort(key=lambda item: (item[1], item[0]), reverse=True)
    negative.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return positive, negative


def _outcome_text(outcome: OutcomeRecord) -> str:
    if outcome.target_before_stop is True:
        return "TARGET_BEFORE_STOP"
    if outcome.target_before_stop is False:
        return "TARGET_NOT_REACHED_BEFORE_STOP"
    return "PENDING_OR_INCOMPLETE"


def _explanation(
    symbol: str,
    snapshot: FeatureSnapshot,
    outcome: OutcomeRecord,
    stable_features: tuple[str, ...],
    missing_groups: tuple[str, ...],
) -> str:
    if symbol in {"KALYANKJIL", "PCJEWELLER"}:
        separation = (
            "Point-in-time differentiation is supported by stable features: "
            + ", ".join(stable_features[:5])
            if stable_features
            else (
                "Current point-in-time features do not provide stable evidence that "
                "separates this case from failed lookalikes."
            )
        )
    else:
        separation = (
            "Stable differentiating evidence was available at onset."
            if stable_features
            else "No stable standalone differentiator was established."
        )
    missing = ", ".join(missing_groups) if missing_groups else "none"
    return (
        f"At {snapshot.onset_date}, Alpha could use only information dated no later "
        f"than the onset. {_outcome_text(outcome)}. {separation} Missing feature "
        f"groups: {missing}."
    )


def _unavailable(symbol: str) -> CaseStudy:
    return CaseStudy(
        symbol=symbol,
        onset_id=None,
        onset_date=None,
        outcome="UNAVAILABLE",
        canonical_result="UNAVAILABLE",
        top_positive_features=(),
        top_negative_features=(),
        population_percentiles=(),
        missing_feature_groups=(),
        differentiation_available_point_in_time=False,
        explanation=(
            "No labelled point-in-time market opportunity is available for this symbol."
        ),
    )


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


__all__ = ["FeatureCaseStudyEngine", "MANDATORY_SYMBOLS"]
