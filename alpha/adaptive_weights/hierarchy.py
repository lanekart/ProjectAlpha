from __future__ import annotations

from alpha.adaptive_weights.models import (
    ConditionalWeightPolicy,
    HierarchyLevel,
    ResolvedWeightSet,
    canonical_weight_set,
)


class ConditionalWeightResolver:
    def resolve(
        self,
        policy: ConditionalWeightPolicy,
        *,
        setup: str | None,
        regime: str | None,
        horizon: str | None,
    ) -> ResolvedWeightSet:
        candidates = {item.key: item for item in policy.conditionals}
        ordered = (
            ((setup, regime, None), HierarchyLevel.SETUP_REGIME),
            ((setup, None, None), HierarchyLevel.SETUP),
            ((None, regime, None), HierarchyLevel.REGIME),
            ((None, None, horizon), HierarchyLevel.HORIZON),
        )
        for key, level in ordered:
            if (
                key in candidates
                and candidates[key].sample_size >= policy.minimum_sample_size
            ):
                return ResolvedWeightSet(
                    weights=candidates[key].weights,
                    hierarchy_level=level,
                    matched_condition="|".join(value or "ANY" for value in key),
                )
        if policy.universal is not None:
            return ResolvedWeightSet(
                weights=policy.universal,
                hierarchy_level=HierarchyLevel.UNIVERSAL_ADAPTIVE,
                matched_condition="universal adaptive research policy",
            )
        return ResolvedWeightSet(
            weights=canonical_weight_set(),
            hierarchy_level=HierarchyLevel.CANONICAL,
            matched_condition="immutable canonical fallback",
        )


__all__ = ["ConditionalWeightResolver"]
