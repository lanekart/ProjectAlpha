from __future__ import annotations

from decimal import Decimal

from alpha.market_dna.models import (
    DNAEvidenceClass,
    FeatureDefinition,
    FeatureKind,
    FeatureQuality,
)
from alpha.strategy_discovery.feature_manifest import FeatureManifest


class MarketDNAFeatureManifest:
    """DNA metadata layered over the existing point-in-time allow-list."""

    def __init__(self, source: FeatureManifest | None = None) -> None:
        self.source = source or FeatureManifest()
        self._definitions = _build(self.source)
        self._by_id = {item.feature_id: item for item in self._definitions}

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return self._definitions

    @property
    def discovery_features(self) -> tuple[FeatureDefinition, ...]:
        return tuple(item for item in self._definitions if item.discovery_permitted)

    def require(self, feature_id: str) -> FeatureDefinition:
        definition = self._by_id.get(feature_id)
        if definition is None:
            raise ValueError(f"feature is not declared: {feature_id}")
        return definition


def _build(source: FeatureManifest) -> tuple[FeatureDefinition, ...]:
    thresholds: dict[str, tuple[Decimal, ...]] = {
        "strategy_score": (Decimal("40"), Decimal("60"), Decimal("75")),
        "stop_distance_pct": (Decimal("5"), Decimal("10")),
        "reward_risk": (Decimal("1.5"), Decimal("2"), Decimal("3")),
        "price_component": (Decimal("0.45"), Decimal("0.55"), Decimal("0.65")),
        "volume_component": (Decimal("0.45"), Decimal("0.55"), Decimal("0.65")),
        "candle_component": (Decimal("0.45"), Decimal("0.55"), Decimal("0.65")),
    }
    continuous = frozenset(
        {
            "strategy_score",
            "entry_price",
            "stop_distance_pct",
            "reward_risk",
            "price_component",
            "volume_component",
            "candle_component",
        }
    )
    booleans = frozenset(
        {"raw_approved", "long_trade_permission", "complete_trade_plan"}
    )
    caution = frozenset(
        {
            "entry_price",
            "price_component",
            "volume_component",
            "candle_component",
        }
    )
    output: list[FeatureDefinition] = []
    for item in source.definitions:
        quality = (
            FeatureQuality.QUARANTINED
            if not item.usable_for_discovery
            else FeatureQuality.USABLE_WITH_CAUTION
            if item.name in caution
            else FeatureQuality.USABLE
        )
        known = () if item.quarantine_reason is None else (item.quarantine_reason,)
        output.append(
            FeatureDefinition(
                feature_id=item.name,
                name=item.name.replace("_", " ").title(),
                kind=(
                    FeatureKind.CONTINUOUS
                    if item.name in continuous
                    else FeatureKind.BOOLEAN
                    if item.name in booleans
                    else FeatureKind.CATEGORICAL
                ),
                unit=item.unit,
                valid_range=_range(item.name),
                timestamp_semantics=item.timestamp_semantics,
                missing_value_treatment=item.missing_value_treatment.value,
                provenance=item.source,
                evidence_class=DNAEvidenceClass.RECONSTRUCTED,
                threshold_grid=thresholds.get(item.name, ()),
                lineage_overlaps=tuple(sorted(item.known_lineage_overlap)),
                known_defects=known,
                base_quality=quality,
                permitted_with_caution=(
                    quality is FeatureQuality.USABLE_WITH_CAUTION
                    and item.name != "entry_price"
                ),
            )
        )
    return tuple(output)


def _range(feature_id: str) -> str:
    if feature_id == "strategy_score":
        return "0..100"
    if feature_id in {"price_component", "volume_component", "candle_component"}:
        return "0..1"
    if feature_id in {"stop_distance_pct", "reward_risk", "entry_price"}:
        return ">=0"
    return "declared categories"


__all__ = ["MarketDNAFeatureManifest"]
