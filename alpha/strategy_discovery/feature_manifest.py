from __future__ import annotations

import json
from hashlib import sha256

from alpha.strategy_discovery.models import (
    FeatureDefinition,
    FeatureValidity,
    MissingValueTreatment,
)


class FeatureManifest:
    """Explicit allow-list and quarantine ledger for point-in-time features."""

    def __init__(self) -> None:
        self._definitions = _definitions()
        self._by_name = {item.name: item for item in self._definitions}

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return self._definitions

    @property
    def usable_feature_names(self) -> tuple[str, ...]:
        return tuple(
            item.name for item in self._definitions if item.usable_for_discovery
        )

    @property
    def quarantined_features(self) -> tuple[FeatureDefinition, ...]:
        return tuple(
            item
            for item in self._definitions
            if item.validity is FeatureValidity.QUARANTINED
        )

    @property
    def manifest_hash(self) -> str:
        payload = [
            {
                "name": item.name,
                "source": item.source,
                "timestamp_semantics": item.timestamp_semantics,
                "unit": item.unit,
                "missing_value_treatment": item.missing_value_treatment.value,
                "available_at_decision_time": item.available_at_decision_time,
                "validity": item.validity.value,
                "quarantine_reason": item.quarantine_reason,
                "same_source_group": item.same_source_group,
                "known_lineage_overlap": list(item.known_lineage_overlap),
            }
            for item in self._definitions
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()

    def require_usable(self, feature_name: str) -> FeatureDefinition:
        definition = self._by_name.get(feature_name)
        if definition is None:
            raise ValueError(f"feature is not declared: {feature_name}")
        if not definition.usable_for_discovery:
            reason = definition.quarantine_reason or definition.validity.value
            raise ValueError(f"feature is quarantined: {feature_name}: {reason}")
        return definition

    def validate_strategy_features(self, features: tuple[str, ...]) -> None:
        for name in features:
            self.require_usable(name)


def _definitions() -> tuple[FeatureDefinition, ...]:
    decision = "Frozen on CandidateDecisionRecord.created_at; before future outcome."
    indicator_source = "candidate_learning.CandidateDecisionRecord.indicator_scores"
    return (
        _valid("strategy_score", "candidate decision record", decision, "points"),
        _valid("final_verdict", "candidate decision record", decision, "category"),
        _valid("raw_approved", "candidate decision record", decision, "boolean"),
        _valid("confidence", "candidate decision record", decision, "category"),
        _valid("data_quality", "candidate decision record", decision, "category"),
        _valid("setup_type", "candidate decision record", decision, "category"),
        _valid("entry_timing_state", "candidate decision record", decision, "category"),
        _valid(
            "long_trade_permission", "candidate decision record", decision, "boolean"
        ),
        _valid("complete_trade_plan", "candidate decision record", decision, "boolean"),
        _valid("entry_price", "candidate decision record", decision, "INR"),
        _valid("stop_distance_pct", "candidate decision record", decision, "percent"),
        _valid("reward_risk", "candidate decision record", decision, "ratio"),
        _valid(
            "price_component",
            indicator_source,
            decision,
            "normalized score",
            group="recommendation-components",
            overlaps=("strategy_score",),
        ),
        _valid(
            "volume_component",
            indicator_source,
            decision,
            "normalized score",
            group="recommendation-components",
            overlaps=("strategy_score", "price_component"),
        ),
        _valid(
            "candle_component",
            indicator_source,
            decision,
            "normalized score",
            group="recommendation-components",
            overlaps=("strategy_score", "price_component"),
        ),
        _quarantined(
            "retracement_component",
            indicator_source,
            decision,
            "normalized score",
            "Previously inversely predictive; calibration direction is unresolved.",
            group="recommendation-components",
        ),
        _quarantined(
            "market_regime",
            "candidate market-state snapshot",
            decision,
            "category",
            "Reference-label scale defect invalidates predictive-quality evidence.",
        ),
        _quarantined(
            "sector",
            "historical sector membership",
            decision,
            "category",
            "Authoritative point-in-time historical sector membership is unavailable.",
        ),
        _quarantined(
            "realised_return_pct",
            "future outcome window",
            "Known only after the decision and used exclusively as an outcome.",
            "percent",
            "Future-derived outcome fields cannot be discovery features.",
        ),
        _quarantined(
            "mfe_pct",
            "future outcome window",
            "Known only after the decision and used exclusively as an outcome.",
            "percent",
            "Future-derived outcome fields cannot be discovery features.",
        ),
        _quarantined(
            "mae_pct",
            "future outcome window",
            "Known only after the decision and used exclusively as an outcome.",
            "percent",
            "Future-derived outcome fields cannot be discovery features.",
        ),
    )


def _valid(
    name: str,
    source: str,
    semantics: str,
    unit: str,
    *,
    group: str | None = None,
    overlaps: tuple[str, ...] = (),
) -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        source=source,
        timestamp_semantics=semantics,
        unit=unit,
        missing_value_treatment=MissingValueTreatment.EXCLUDE_CONDITION,
        available_at_decision_time=True,
        validity=FeatureValidity.VALID,
        quarantine_reason=None,
        same_source_group=group,
        known_lineage_overlap=overlaps,
    )


def _quarantined(
    name: str,
    source: str,
    semantics: str,
    unit: str,
    reason: str,
    *,
    group: str | None = None,
) -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        source=source,
        timestamp_semantics=semantics,
        unit=unit,
        missing_value_treatment=MissingValueTreatment.REJECT_ROW,
        available_at_decision_time=not any(
            marker in semantics.lower() for marker in ("future", "after the decision")
        ),
        validity=FeatureValidity.QUARANTINED,
        quarantine_reason=reason,
        same_source_group=group,
    )


__all__ = ["FeatureManifest"]
