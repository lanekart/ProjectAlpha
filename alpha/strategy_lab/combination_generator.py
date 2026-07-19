from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from alpha.strategy_discovery.candidate_strategy_generator import (
    CandidateStrategyGenerator,
)
from alpha.strategy_discovery.models import DiscoveryDataset, DiscoveryRunConfig
from alpha.strategy_lab.indicator_registry import IndicatorRegistry
from alpha.strategy_lab.models import (
    EntryRule,
    ExecutionAssumptionProfile,
    LabEvidenceClass,
    LabStrategySpecification,
    SearchSpaceSummary,
    StopRule,
    TargetRule,
)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    maximum_components: int = 3
    maximum_variants_per_family: int = 25
    family: str | None = None
    indicators: tuple[str, ...] = ()
    entry_rule: EntryRule = EntryRule.RECORDED_REFERENCE
    stop_rule: StopRule = StopRule.RECORDED_PLAN
    target_rule: TargetRule = TargetRule.RECORDED_PLAN
    holding_period_days: int = 20
    start_date: date | None = None
    end_date: date | None = None
    symbols: tuple[str, ...] = ()
    setups: tuple[str, ...] = ()


class CombinationGenerator:
    """Compose the existing bounded generator with execution-plan dimensions."""

    def __init__(
        self,
        *,
        generator: CandidateStrategyGenerator | None = None,
        indicators: IndicatorRegistry | None = None,
    ) -> None:
        self.generator = generator or CandidateStrategyGenerator()
        self.indicators = indicators or IndicatorRegistry()

    def generate(
        self,
        *,
        dataset: DiscoveryDataset,
        request: GenerationRequest,
        execution_profile: ExecutionAssumptionProfile,
    ) -> tuple[tuple[LabStrategySpecification, ...], SearchSpaceSummary]:
        if request.maximum_components < 1 or request.maximum_components > 5:
            raise ValueError("maximum components must be between 1 and 5")
        for indicator in request.indicators:
            self.indicators.require_usable(indicator)
        config = DiscoveryRunConfig(
            maximum_conditions_per_strategy=request.maximum_components,
            maximum_variants_per_family=request.maximum_variants_per_family,
        )
        base, base_manifest = self.generator.generate(dataset=dataset, config=config)
        filtered = tuple(
            item
            for item in base
            if (request.family is None or item.family.value == request.family)
            and (
                not request.indicators
                or set(request.indicators)
                <= {condition.feature_name for condition in item.conditions}
            )
        )
        drafts: list[LabStrategySpecification] = []
        for index, item in enumerate(filtered, start=1):
            payload = {
                "source_hash": item.strategy_hash,
                "entry": request.entry_rule.value,
                "stop": request.stop_rule.value,
                "target": request.target_rule.value,
                "holding": request.holding_period_days,
                "execution": execution_profile.profile_id,
                "dataset": dataset.dataset_version,
            }
            strategy_hash = sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            drafts.append(
                LabStrategySpecification(
                    strategy_id=f"LAB_STRATEGY_{index:04d}_{strategy_hash[:8]}",
                    strategy_hash=strategy_hash,
                    source_strategy_version=item.strategy_version,
                    name=item.name,
                    family=item.family.value,
                    conditions=item.conditions,
                    entry_rule=request.entry_rule,
                    stop_rule=request.stop_rule,
                    target_rule=request.target_rule,
                    holding_period_days=request.holding_period_days,
                    execution_profile_id=execution_profile.profile_id,
                    dataset_version=dataset.dataset_version,
                    evidence_class=LabEvidenceClass.RECONSTRUCTED,
                    benchmark=item.benchmark,
                )
            )
        lineage_flags = sum(
            _has_lineage_overlap(item, self.indicators) for item in drafts
        )
        family_counts = Counter(item.family for item in drafts)
        manifest_payload = {
            "strategies": [item.strategy_hash for item in drafts],
            "base_search": base_manifest.search_space_hash,
            "request": {
                "max": request.maximum_components,
                "family": request.family,
                "indicators": request.indicators,
                "entry": request.entry_rule.value,
                "stop": request.stop_rule.value,
                "target": request.target_rule.value,
                "holding": request.holding_period_days,
            },
        }
        search_hash = sha256(
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return tuple(drafts), SearchSpaceSummary(
            search_space_hash=search_hash,
            total_trials=len(drafts),
            generated_strategies=len(drafts),
            duplicate_rules_removed=max(0, base_manifest.total_variants - len(base)),
            impossible_rules_rejected=0,
            lineage_redundancy_flags=lineage_flags,
            maximum_components=request.maximum_components,
            maximum_variants_per_family=request.maximum_variants_per_family,
            family_counts=dict(family_counts),
            rules_tested=(
                request.entry_rule.value,
                request.stop_rule.value,
                request.target_rule.value,
                f"HOLD_{request.holding_period_days}_DAYS",
            ),
        )


def _has_lineage_overlap(
    strategy: LabStrategySpecification,
    registry: IndicatorRegistry,
) -> int:
    selected = {item.feature_name for item in strategy.conditions}
    definitions = {item.canonical_id: item for item in registry.definitions}
    for name in selected:
        definition = definitions.get(name)
        if definition is not None and selected & set(definition.lineage_overlaps):
            return 1
    return 0


__all__ = ["CombinationGenerator", "GenerationRequest"]
