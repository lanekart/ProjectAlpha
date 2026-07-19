from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from itertools import combinations

from alpha.strategy_discovery.feature_manifest import FeatureManifest
from alpha.strategy_discovery.models import (
    ConditionOperator,
    DiscoveryDataset,
    DiscoveryRunConfig,
    SearchSpaceManifest,
    StrategyCondition,
    StrategyFamily,
    StrategySpecification,
)
from alpha.strategy_discovery.strategy_family_registry import StrategyFamilyRegistry


class CandidateStrategyGenerator:
    """Generate a deterministic, bounded set of auditable strategies."""

    def __init__(
        self,
        *,
        family_registry: StrategyFamilyRegistry | None = None,
        feature_manifest: FeatureManifest | None = None,
    ) -> None:
        self.family_registry = family_registry or StrategyFamilyRegistry()
        self.feature_manifest = feature_manifest or FeatureManifest()

    def generate(
        self,
        *,
        dataset: DiscoveryDataset,
        config: DiscoveryRunConfig,
    ) -> tuple[tuple[StrategySpecification, ...], SearchSpaceManifest]:
        by_family = self._conditions_by_family(dataset, config)
        drafts: list[
            tuple[str, StrategyFamily, tuple[StrategyCondition, ...], bool, str]
        ] = []
        definitions = {item.family: item for item in self.family_registry.definitions}
        for family in sorted(by_family, key=lambda item: item.value):
            variants = by_family[family][: config.maximum_variants_per_family]
            definition = definitions[family]
            for index, conditions in enumerate(variants, start=1):
                if (
                    len(conditions) > config.maximum_conditions_per_strategy
                    and not definition.benchmark
                ):
                    raise ValueError("strategy exceeds configured condition bound")
                self.feature_manifest.validate_strategy_features(
                    tuple(condition.feature_name for condition in conditions)
                )
                drafts.append(
                    (
                        f"{family.value} {index}",
                        family,
                        conditions,
                        definition.benchmark,
                        definition.description,
                    )
                )
        hashed = tuple(
            (
                _strategy_hash(family, conditions),
                name,
                family,
                conditions,
                benchmark,
                description,
            )
            for name, family, conditions, benchmark, description in drafts
        )
        unique = {
            item[0]: item
            for item in sorted(hashed, key=lambda item: (item[2].value, item[0]))
        }
        strategies = tuple(
            StrategySpecification(
                strategy_version=f"STRATEGY_RESEARCH_V{index:03d}",
                strategy_hash=item[0],
                name=item[1],
                family=item[2],
                conditions=item[3],
                benchmark=item[4],
                description=item[5],
            )
            for index, item in enumerate(unique.values(), start=1)
        )
        family_counts = Counter(item.family.value for item in strategies)
        search_hash = sha256(
            json.dumps(
                [
                    {
                        "hash": item.strategy_hash,
                        "family": item.family.value,
                        "conditions": [
                            condition.canonical_key for condition in item.conditions
                        ],
                    }
                    for item in strategies
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        manifest = SearchSpaceManifest(
            manifest_version="bounded-strategy-search-v1",
            maximum_conditions_per_strategy=config.maximum_conditions_per_strategy,
            maximum_variants_per_family=config.maximum_variants_per_family,
            family_variant_counts=dict(family_counts),
            total_variants=len(strategies),
            search_space_hash=search_hash,
            feature_manifest_hash=self.feature_manifest.manifest_hash,
            rationale=(
                "Declared interpretable families, fixed observed-independent numeric "
                "boundaries, and observed categorical values capped per family."
            ),
        )
        return strategies, manifest

    def _conditions_by_family(
        self,
        dataset: DiscoveryDataset,
        config: DiscoveryRunConfig,
    ) -> dict[StrategyFamily, tuple[tuple[StrategyCondition, ...], ...]]:
        score = tuple(
            (_ge("strategy_score", value),)
            for value in ("50", "60", "70", "75", "80", "85", "90")
        )
        price = tuple(
            (_ge("price_component", value),) for value in ("0.55", "0.65", "0.75")
        )
        price_volume = tuple(
            (_ge("price_component", price_value), _ge("volume_component", volume_value))
            for price_value, volume_value in (
                ("0.55", "0.50"),
                ("0.65", "0.55"),
                ("0.70", "0.60"),
                ("0.75", "0.65"),
            )
        )
        setups = tuple(
            (_eq("setup_type", value),)
            for value in _top_categories(dataset, "setup_type", 10)
        )
        timing = tuple(
            (_eq("entry_timing_state", value),)
            for value in _top_categories(dataset, "entry_timing_state", 8)
        )
        trade_plan = (
            (_true("complete_trade_plan"),),
            (_true("complete_trade_plan"), _ge("reward_risk", "2")),
            (_true("complete_trade_plan"), _le("stop_distance_pct", "15")),
        )
        signal_subset = (
            (_ge("price_component", "0.65"), _ge("candle_component", "0.55")),
            (_ge("volume_component", "0.60"), _ge("candle_component", "0.55")),
            (_ge("price_component", "0.65"), _ge("volume_component", "0.55")),
        )
        gate_subset = (
            (_eq("final_verdict", "BUY"),),
            (_eq("confidence", "HIGH"),),
            (_eq("data_quality", "COMPLETE"),),
            (_true("raw_approved"),),
            (_eq("final_verdict", "BUY"), _eq("confidence", "HIGH")),
            (_true("raw_approved"), _eq("data_quality", "COMPLETE")),
        )
        base = (
            _ge("strategy_score", "70"),
            _ge("price_component", "0.65"),
            _ge("volume_component", "0.55"),
            _ge("candle_component", "0.55"),
            _eq("confidence", "HIGH"),
            _true("complete_trade_plan"),
            _eq("data_quality", "COMPLETE"),
        )
        conjunctions: list[tuple[StrategyCondition, ...]] = []
        for count in range(2, config.maximum_conditions_per_strategy + 1):
            conjunctions.extend(combinations(base, count))
        return {
            StrategyFamily.SCORE_THRESHOLD: score,
            StrategyFamily.PRICE_STRUCTURE: price,
            StrategyFamily.PRICE_VOLUME: price_volume,
            StrategyFamily.SETUP_SPECIFIC: setups,
            StrategyFamily.ENTRY_TIMING: timing,
            StrategyFamily.TRADE_PLAN_QUALITY: trade_plan,
            StrategyFamily.SIGNAL_COMPONENT_SUBSET: signal_subset,
            StrategyFamily.APPROVAL_GATE_SUBSET: gate_subset,
            StrategyFamily.SIMPLE_CONJUNCTION: tuple(conjunctions),
            StrategyFamily.APPROVAL_POLICY_V1: ((),),
            StrategyFamily.RAW_RECORDED_APPROVAL: ((),),
            StrategyFamily.NO_TRADE: ((),),
        }


def _top_categories(
    dataset: DiscoveryDataset,
    feature: str,
    limit: int,
) -> tuple[str, ...]:
    counts = Counter(
        row.features[feature]
        for row in dataset.rows
        if row.features.get(feature) not in {None, "UNAVAILABLE", "unavailable"}
    )
    return tuple(
        value
        for value, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :limit
        ]
    )


def _strategy_hash(
    family: StrategyFamily,
    conditions: tuple[StrategyCondition, ...],
) -> str:
    payload = {
        "family": family.value,
        "conditions": sorted(condition.canonical_key for condition in conditions),
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _ge(name: str, value: str) -> StrategyCondition:
    return StrategyCondition(name, ConditionOperator.GREATER_THAN_OR_EQUAL, value)


def _le(name: str, value: str) -> StrategyCondition:
    return StrategyCondition(name, ConditionOperator.LESS_THAN_OR_EQUAL, value)


def _eq(name: str, value: str) -> StrategyCondition:
    return StrategyCondition(name, ConditionOperator.EQUAL, value)


def _true(name: str) -> StrategyCondition:
    return StrategyCondition(name, ConditionOperator.IS_TRUE, "true")


__all__ = ["CandidateStrategyGenerator"]
