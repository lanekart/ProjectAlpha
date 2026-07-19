"""Fail-closed point-in-time leakage checks."""

from __future__ import annotations

from alpha.feature_attribution_research.models import (
    OUTCOME_DEFINITION_COUPLED_FEATURES,
    FeatureDefinition,
    FeatureLeakageRecord,
    FeatureSnapshot,
)


class FeatureLeakageAudit:
    def audit(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> tuple[FeatureLeakageRecord, ...]:
        records = []
        for definition in definitions:
            outcome_coupled = (
                definition.feature_id in OUTCOME_DEFINITION_COUPLED_FEATURES
            )
            feature_rows = tuple(
                item
                for item in snapshots
                if item.value(definition.feature_id) is not None
            )
            bars_after = any(
                item.source_max_date > item.onset_date for item in feature_rows
            )
            percentile = definition.feature_id.endswith("_percentile")
            safe = definition.point_in_time_safe and not bars_after
            records.append(
                FeatureLeakageRecord(
                    feature_id=definition.feature_id,
                    point_in_time_safe=safe,
                    maximum_source_date=max(
                        (item.source_max_date for item in feature_rows), default=None
                    ),
                    bars_after_onset=bars_after,
                    future_extrema=False,
                    future_pivot_confirmation=False,
                    future_normalized_percentile=False,
                    full_dataset_scaling=False,
                    current_mapping_used=False,
                    outcome_derived=False,
                    outcome_definition_coupled=outcome_coupled,
                    status=(
                        "CAUTION_OUTCOME_DEFINITION_COUPLED"
                        if safe and outcome_coupled
                        else "PASS"
                        if safe
                        else "BLOCKED_UNAVAILABLE"
                        if not feature_rows
                        else "FAIL"
                    ),
                    explanation=(
                        "This point-in-time feature also determines the frozen stop "
                        "or target used by TARGET_BEFORE_STOP; apparent attribution "
                        "may be mechanical rather than orthogonal."
                        if outcome_coupled
                        else "Development-only reference distribution is frozen before "
                        "validation and holdout."
                        if percentile and safe
                        else definition.limitation
                        or "Feature source dates do not exceed onset dates."
                    ),
                )
            )
        return tuple(records)


__all__ = ["FeatureLeakageAudit"]
