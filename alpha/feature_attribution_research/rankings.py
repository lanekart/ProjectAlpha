"""Separate evidence rankings, confidence tiers, and readable feature cards."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    EvidencePartition,
    FeatureCard,
    FeatureConfidenceTier,
    FeatureDefinition,
    FeatureLeakageRecord,
    FeatureQualityFlag,
    FeatureQualityRecord,
    FeatureRanking,
    FeatureStabilityScore,
    InformationDecayResult,
    OrthogonalEdgeResult,
    RedundancyClassification,
    RedundancyResult,
    ResearchConclusion,
    StabilityClassification,
)


class FeatureRankingEngine:
    def build(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        quality: tuple[FeatureQualityRecord, ...],
        leakage: tuple[FeatureLeakageRecord, ...],
        univariate: tuple[AttributionResult, ...],
        redundancy: tuple[RedundancyResult, ...],
        orthogonal: tuple[OrthogonalEdgeResult, ...],
        stability: tuple[FeatureStabilityScore, ...],
        information_decay: tuple[InformationDecayResult, ...],
    ) -> tuple[tuple[FeatureRanking, ...], tuple[FeatureCard, ...]]:
        quality_by_id = {item.feature_id: item for item in quality}
        leakage_by_id = {item.feature_id: item for item in leakage}
        stability_by_id = {item.feature_id: item for item in stability}
        orthogonal_by_id = {
            item.feature_id: item
            for item in orthogonal
            if not item.feature_id.startswith("__")
        }
        primary = {
            (item.feature_id, item.partition): item
            for item in univariate
            if item.outcome_id == "TARGET_BEFORE_STOP"
        }
        redundant = _redundant_features(redundancy, primary)
        tier_by_id = {
            item.feature_id: _tier(
                item,
                quality_by_id.get(item.feature_id),
                stability_by_id.get(item.feature_id),
                primary.get((item.feature_id, EvidencePartition.HOLDOUT)),
                orthogonal_by_id.get(item.feature_id),
                item.feature_id in redundant,
                leakage_by_id.get(item.feature_id),
            )
            for item in definitions
        }
        conclusion_by_id = {
            item.feature_id: _conclusion(
                tier_by_id[item.feature_id],
                stability_by_id.get(item.feature_id),
                item.feature_id in redundant,
                bool(
                    leakage_by_id.get(item.feature_id)
                    and leakage_by_id[item.feature_id].outcome_definition_coupled
                ),
            )
            for item in definitions
        }
        rankings: list[FeatureRanking] = []
        ranking_values: tuple[
            tuple[str, Callable[[FeatureDefinition], Decimal | None]], ...
        ] = (
            (
                "univariate_strength",
                lambda definition: _auc_strength(
                    primary.get((definition.feature_id, None))
                ),
            ),
            (
                "holdout_strength",
                lambda definition: _auc_strength(
                    primary.get((definition.feature_id, EvidencePartition.HOLDOUT))
                ),
            ),
            (
                "stability",
                lambda definition: _stability_value(
                    stability_by_id.get(definition.feature_id)
                ),
            ),
            (
                "orthogonal_incremental_value",
                lambda definition: _orthogonal_value(
                    orthogonal_by_id.get(definition.feature_id)
                ),
            ),
            (
                "data_quality",
                lambda definition: _data_quality_value(
                    quality_by_id.get(definition.feature_id)
                ),
            ),
            (
                "operational_availability",
                lambda definition: (
                    Decimal("1") if definition.point_in_time_safe else Decimal("0")
                ),
            ),
        )
        for ranking_name, value_function in ranking_values:
            ordered = sorted(
                (
                    (definition, value_function(definition))
                    for definition in definitions
                ),
                key=lambda row: (
                    row[1] is not None,
                    row[1] or Decimal("-999"),
                    row[0].feature_id,
                ),
                reverse=True,
            )
            for rank, (definition, value) in enumerate(ordered, start=1):
                conclusion = conclusion_by_id[definition.feature_id]
                rankings.append(
                    FeatureRanking(
                        feature_id=definition.feature_id,
                        ranking_name=ranking_name,
                        rank=rank,
                        value=value,
                        confidence_tier=tier_by_id[definition.feature_id],
                        conclusion=conclusion,
                        recommendation=_recommendation(conclusion),
                    )
                )
        cards = _cards(
            definitions=definitions,
            quality=quality_by_id,
            leakage=leakage_by_id,
            primary=primary,
            orthogonal=orthogonal_by_id,
            stability=stability_by_id,
            decay=information_decay,
            tiers=tier_by_id,
            conclusions=conclusion_by_id,
        )
        return tuple(rankings), cards


def _cards(
    *,
    definitions: tuple[FeatureDefinition, ...],
    quality: Mapping[str, FeatureQualityRecord],
    leakage: Mapping[str, FeatureLeakageRecord],
    primary: Mapping[tuple[str, EvidencePartition | None], AttributionResult],
    orthogonal: Mapping[str, OrthogonalEdgeResult],
    stability: Mapping[str, FeatureStabilityScore],
    decay: tuple[InformationDecayResult, ...],
    tiers: Mapping[str, FeatureConfidenceTier],
    conclusions: Mapping[str, ResearchConclusion],
) -> tuple[FeatureCard, ...]:
    decay_by_id: dict[str, list[InformationDecayResult]] = {}
    for item in decay:
        decay_by_id.setdefault(item.feature_id, []).append(item)
    cards = []
    for definition in definitions:
        feature_id = definition.feature_id
        development = primary.get((feature_id, EvidencePartition.DEVELOPMENT))
        validation = primary.get((feature_id, EvidencePartition.VALIDATION))
        holdout = primary.get((feature_id, EvidencePartition.HOLDOUT))
        overall = primary.get((feature_id, None))
        stable = stability.get(feature_id)
        orthogonal_row = orthogonal.get(feature_id)
        quality_row = quality.get(feature_id)
        leakage_row = leakage.get(feature_id)
        conclusion = conclusions[feature_id]
        cards.append(
            FeatureCard(
                feature_id=feature_id,
                feature_name=definition.feature_name,
                feature_group=definition.feature_group,
                direction=(
                    AttributionDirection.NO_EVIDENCE
                    if overall is None
                    else overall.direction
                ),
                confidence_tier=tiers[feature_id],
                development_auc=None if development is None else development.auc,
                validation_auc=None if validation is None else validation.auc,
                holdout_auc=None if holdout is None else holdout.auc,
                stability_score=(None if stable is None else stable.overall_stability),
                orthogonal_incremental_auc=(
                    None if orthogonal_row is None else orthogonal_row.incremental_auc
                ),
                information_decay=tuple(
                    sorted(
                        (item.horizon, item.auc)
                        for item in decay_by_id.get(feature_id, ())
                    )
                ),
                data_quality_flags=(
                    (
                        ("OUTCOME_DEFINITION_COUPLED",)
                        if leakage_row is not None
                        and leakage_row.outcome_definition_coupled
                        else ()
                    )
                    if quality_row is None
                    else tuple(item.value for item in quality_row.flags)
                    + (
                        ("OUTCOME_DEFINITION_COUPLED",)
                        if leakage_row is not None
                        and leakage_row.outcome_definition_coupled
                        else ()
                    )
                ),
                conclusion=conclusion,
                recommendation=_recommendation(conclusion),
                evidence_summary=_summary(
                    definition,
                    development,
                    validation,
                    holdout,
                    stable,
                    orthogonal_row,
                ),
            )
        )
    tier_order = {
        FeatureConfidenceTier.A: 0,
        FeatureConfidenceTier.B: 1,
        FeatureConfidenceTier.D: 2,
        FeatureConfidenceTier.C: 3,
        FeatureConfidenceTier.E: 4,
    }
    return tuple(
        sorted(
            cards,
            key=lambda item: (
                tier_order[item.confidence_tier],
                -(item.stability_score or Decimal("-1")),
                -abs((item.holdout_auc or Decimal("0.5")) - Decimal("0.5")),
                -(item.orthogonal_incremental_auc or Decimal("-1")),
                item.feature_id,
            ),
        )[:20]
    )


def _tier(
    definition: FeatureDefinition,
    quality: FeatureQualityRecord | None,
    stability: FeatureStabilityScore | None,
    holdout: AttributionResult | None,
    orthogonal: OrthogonalEdgeResult | None,
    redundant: bool,
    leakage: FeatureLeakageRecord | None,
) -> FeatureConfidenceTier:
    if not definition.point_in_time_safe or quality is None or stability is None:
        return FeatureConfidenceTier.E
    if any(
        item
        in {
            FeatureQualityFlag.ZERO_VARIANCE,
            FeatureQualityFlag.DATA_NOT_POINT_IN_TIME,
            FeatureQualityFlag.HIGH_MISSINGNESS,
        }
        for item in quality.flags
    ):
        return FeatureConfidenceTier.E
    if leakage is not None and leakage.outcome_definition_coupled:
        return FeatureConfidenceTier.E
    if redundant:
        return FeatureConfidenceTier.E
    if stability.classification is StabilityClassification.STABLE_NEGATIVE:
        return FeatureConfidenceTier.D
    if (
        stability.classification is StabilityClassification.STABLE_POSITIVE
        and holdout is not None
        and holdout.auc is not None
        and holdout.auc >= Decimal("0.55")
        and orthogonal is not None
        and orthogonal.incremental_auc is not None
        and orthogonal.incremental_auc > 0
        and orthogonal.incremental_brier_improvement is not None
        and orthogonal.incremental_brier_improvement > 0
        and orthogonal.feature_sign_stability
        and not redundant
    ):
        return FeatureConfidenceTier.A
    if (
        stability.classification is StabilityClassification.STABLE_POSITIVE
        and holdout is not None
        and holdout.auc is not None
        and holdout.direction is AttributionDirection.POSITIVE
    ):
        return FeatureConfidenceTier.B
    if (
        stability.classification is StabilityClassification.CONTEXT_DEPENDENT
        and holdout is not None
        and holdout.auc is not None
        and holdout.direction
        in {AttributionDirection.POSITIVE, AttributionDirection.NEGATIVE}
    ):
        return FeatureConfidenceTier.B
    if stability.classification in {
        StabilityClassification.DATA_QUALITY_BLOCKED,
        StabilityClassification.INSUFFICIENT_EVIDENCE,
        StabilityClassification.HOLDOUT_FAILURE,
        StabilityClassification.DEVELOPMENT_ONLY,
    }:
        return FeatureConfidenceTier.E
    return FeatureConfidenceTier.C


def _conclusion(
    tier: FeatureConfidenceTier,
    stability: FeatureStabilityScore | None,
    redundant: bool,
    outcome_coupled: bool,
) -> ResearchConclusion:
    if redundant or outcome_coupled:
        return ResearchConclusion.FEATURE_IS_REDUNDANT
    if tier is FeatureConfidenceTier.A:
        return ResearchConclusion.FEATURE_HAS_STABLE_EDGE
    if tier is FeatureConfidenceTier.D:
        return ResearchConclusion.FEATURE_IS_INVERSELY_PREDICTIVE
    if tier is FeatureConfidenceTier.B:
        return ResearchConclusion.FEATURE_IS_CONTEXT_DEPENDENT
    if (
        stability is None
        or stability.classification is StabilityClassification.DATA_QUALITY_BLOCKED
    ):
        return ResearchConclusion.FEATURE_IS_DATA_BLOCKED
    if tier is FeatureConfidenceTier.E:
        return ResearchConclusion.FEATURE_IS_UNSTABLE
    return ResearchConclusion.NO_EVIDENCE


def _recommendation(conclusion: ResearchConclusion) -> str:
    return {
        ResearchConclusion.FEATURE_HAS_STABLE_EDGE: (
            "Retain for further validation; do not change production weights."
        ),
        ResearchConclusion.FEATURE_IS_INVERSELY_PREDICTIVE: (
            "Investigate inverse interpretation as a failure-risk feature."
        ),
        ResearchConclusion.FEATURE_IS_REDUNDANT: (
            "Replace composite use with the clearest raw feature in future research."
        ),
        ResearchConclusion.FEATURE_IS_CONTEXT_DEPENDENT: (
            "Test only within the supported context."
        ),
        ResearchConclusion.FEATURE_IS_UNSTABLE: (
            "Keep research-only until chronological evidence improves."
        ),
        ResearchConclusion.FEATURE_IS_DATA_BLOCKED: (
            "Collect better point-in-time historical data."
        ),
        ResearchConclusion.NO_EVIDENCE: (
            "Do not use as a standalone research discriminator."
        ),
    }[conclusion]


def _summary(
    definition: FeatureDefinition,
    development: AttributionResult | None,
    validation: AttributionResult | None,
    holdout: AttributionResult | None,
    stability: FeatureStabilityScore | None,
    orthogonal: OrthogonalEdgeResult | None,
) -> str:
    stability_value = None if stability is None else stability.overall_stability
    orthogonal_value = None if orthogonal is None else orthogonal.incremental_auc
    return (
        f"{definition.feature_name}: development AUC {_value(development)}, "
        f"validation AUC {_value(validation)}, holdout AUC {_value(holdout)}; "
        f"stability {_decimal_value(stability_value)}; "
        f"orthogonal holdout increment {_decimal_value(orthogonal_value)}."
    )


def _redundant_features(
    rows: tuple[RedundancyResult, ...],
    primary: Mapping[tuple[str, EvidencePartition | None], AttributionResult],
) -> set[str]:
    graph: dict[str, set[str]] = {}
    for item in rows:
        if item.classification in {
            RedundancyClassification.HIGHLY_REDUNDANT,
            RedundancyClassification.SAME_SOURCE_DUPLICATE,
        }:
            graph.setdefault(item.feature_a, set()).add(item.feature_b)
            graph.setdefault(item.feature_b, set()).add(item.feature_a)
    result: set[str] = set()
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
            pending.extend(graph.get(current, ()))
        representative = max(
            group,
            key=lambda item: (
                _auc_strength(primary.get((item, EvidencePartition.HOLDOUT)))
                or Decimal("-1"),
                _auc_strength(primary.get((item, None))) or Decimal("-1"),
                item,
            ),
        )
        result.update(group - {representative})
    return result


def _auc_strength(value: AttributionResult | None) -> Decimal | None:
    return (
        None if value is None or value.auc is None else abs(value.auc - Decimal("0.5"))
    )


def _stability_value(value: FeatureStabilityScore | None) -> Decimal | None:
    return None if value is None else value.overall_stability


def _orthogonal_value(value: OrthogonalEdgeResult | None) -> Decimal | None:
    return None if value is None else value.incremental_auc


def _data_quality_value(value: FeatureQualityRecord | None) -> Decimal | None:
    return None if value is None else Decimal("1") - value.missing_rate


def _value(value: AttributionResult | None) -> str:
    return _decimal_value(None if value is None else value.auc)


def _decimal_value(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.4f}"


__all__ = ["FeatureRankingEngine"]
