from __future__ import annotations

from alpha.market_dna.models import FeatureCondition, FeatureDefinition


class LineageAnalysis:
    """Identify same-source overlap without claiming independent contribution."""

    def risks_for_feature(
        self,
        definition: FeatureDefinition,
    ) -> tuple[str, ...]:
        return tuple(
            f"overlaps:{feature_id}" for feature_id in definition.lineage_overlaps
        )

    def interaction_is_confounded(
        self,
        conditions: tuple[FeatureCondition, ...],
        definitions: dict[str, FeatureDefinition],
    ) -> bool:
        feature_ids = {item.feature_id for item in conditions}
        for condition in conditions:
            definition = definitions[condition.feature_id]
            if feature_ids.intersection(definition.lineage_overlaps):
                return True
        return False


__all__ = ["LineageAnalysis"]
