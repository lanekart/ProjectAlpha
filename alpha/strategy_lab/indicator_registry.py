from __future__ import annotations

from alpha.strategy_discovery.feature_manifest import FeatureManifest
from alpha.strategy_discovery.models import FeatureValidity
from alpha.strategy_lab.models import IndicatorDefinition, LabEvidenceClass


class IndicatorRegistry:
    """Expose only declared point-in-time features and their quarantine state."""

    def __init__(self, manifest: FeatureManifest | None = None) -> None:
        self.manifest = manifest or FeatureManifest()
        self._definitions = tuple(
            _definition(item) for item in self.manifest.definitions
        )
        self._by_id = {item.canonical_id: item for item in self._definitions}

    @property
    def definitions(self) -> tuple[IndicatorDefinition, ...]:
        return self._definitions

    @property
    def usable(self) -> tuple[IndicatorDefinition, ...]:
        return tuple(item for item in self._definitions if not item.quarantined)

    @property
    def quarantined(self) -> tuple[IndicatorDefinition, ...]:
        return tuple(item for item in self._definitions if item.quarantined)

    def require_usable(self, canonical_id: str) -> IndicatorDefinition:
        item = self._by_id.get(canonical_id)
        if item is None:
            raise ValueError(
                f"indicator is not historically registered: {canonical_id}"
            )
        if item.quarantined:
            raise ValueError(
                f"indicator is quarantined: {canonical_id}: {item.quarantine_reason}"
            )
        return item


def _definition(item: object) -> IndicatorDefinition:
    from alpha.strategy_discovery.models import FeatureDefinition

    if not isinstance(item, FeatureDefinition):
        raise TypeError("feature definition required")
    category = _category(item.name)
    valid_range = _range(item.unit)
    quarantined = item.validity is not FeatureValidity.VALID
    defects = () if item.quarantine_reason is None else (item.quarantine_reason,)
    return IndicatorDefinition(
        canonical_id=item.name,
        name=item.name.replace("_", " ").title(),
        category=category,
        unit=item.unit,
        valid_range=valid_range,
        timestamp_semantics=item.timestamp_semantics,
        missing_data_treatment=item.missing_value_treatment.value,
        provenance=item.source,
        historical_availability=(
            "AVAILABLE_POINT_IN_TIME"
            if item.available_at_decision_time
            else "UNAVAILABLE"
        ),
        evidence_class=LabEvidenceClass.RECONSTRUCTED,
        lineage_overlaps=item.known_lineage_overlap,
        known_defects=defects,
        quarantined=quarantined,
        quarantine_reason=item.quarantine_reason,
    )


def _category(name: str) -> str:
    categories = {
        "strategy_score": "RECOMMENDATION_SCORE",
        "final_verdict": "RECOMMENDATION",
        "raw_approved": "APPROVAL_GATE",
        "confidence": "CONFIDENCE",
        "data_quality": "DATA_QUALITY",
        "setup_type": "SETUP",
        "entry_timing_state": "ENTRY_TIMING",
        "long_trade_permission": "APPROVAL_GATE",
        "complete_trade_plan": "TRADE_PLAN",
        "entry_price": "ENTRY",
        "stop_distance_pct": "RISK_VOLATILITY",
        "reward_risk": "TRADE_PLAN",
        "price_component": "PRICE_STRUCTURE",
        "volume_component": "VOLUME",
        "candle_component": "CANDLE",
        "retracement_component": "RETRACEMENT",
        "market_regime": "MARKET_REGIME",
        "sector": "SECTOR",
        "realised_return_pct": "FUTURE_OUTCOME",
        "mfe_pct": "FUTURE_OUTCOME",
        "mae_pct": "FUTURE_OUTCOME",
    }
    return categories.get(name, "OTHER")


def _range(unit: str) -> str:
    normalized = unit.lower()
    if "normalized" in normalized:
        return "0 to 1"
    if unit == "boolean":
        return "true or false"
    if unit == "points":
        return "0 to 100"
    if unit in {"percent", "ratio", "INR"}:
        return "non-negative where structurally applicable"
    return "declared categories only"


__all__ = ["IndicatorRegistry"]
