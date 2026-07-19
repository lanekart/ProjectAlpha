from __future__ import annotations

from dataclasses import dataclass

from alpha.strategy_discovery.models import StrategyFamily


@dataclass(frozen=True, slots=True)
class StrategyFamilyDefinition:
    family: StrategyFamily
    description: str
    interpretable: bool
    benchmark: bool = False


class StrategyFamilyRegistry:
    """Declared, bounded registry of permitted strategy families."""

    def __init__(self) -> None:
        self._definitions: dict[StrategyFamily, StrategyFamilyDefinition] = {}
        for definition in _initial_definitions():
            self.register(definition)

    def register(self, definition: StrategyFamilyDefinition) -> None:
        if definition.family in self._definitions:
            raise ValueError(f"strategy family already registered: {definition.family}")
        if not definition.interpretable:
            raise ValueError("initial discovery families must be interpretable")
        self._definitions[definition.family] = definition

    @property
    def definitions(self) -> tuple[StrategyFamilyDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: item.value)
        )


def _initial_definitions() -> tuple[StrategyFamilyDefinition, ...]:
    descriptions = {
        StrategyFamily.SCORE_THRESHOLD: "Minimum recommendation-score policies.",
        StrategyFamily.PRICE_STRUCTURE: "Price-component threshold policies.",
        StrategyFamily.PRICE_VOLUME: "Joint price and volume confirmation.",
        StrategyFamily.SETUP_SPECIFIC: "One recorded setup type at a time.",
        StrategyFamily.ENTRY_TIMING: "Recorded entry-timing state policies.",
        StrategyFamily.TRADE_PLAN_QUALITY: "Complete and risk-qualified plans.",
        StrategyFamily.SIGNAL_COMPONENT_SUBSET: "Small technical evidence subsets.",
        StrategyFamily.APPROVAL_GATE_SUBSET: "Auditable subsets of incumbent gates.",
        StrategyFamily.SIMPLE_CONJUNCTION: "Bounded conjunctions of simple conditions.",
        StrategyFamily.APPROVAL_POLICY_V1: "Frozen institutional approval benchmark.",
        StrategyFamily.RAW_RECORDED_APPROVAL: "Recorded raw approval benchmark.",
        StrategyFamily.NO_TRADE: "Zero-exposure benchmark.",
    }
    benchmarks = {
        StrategyFamily.APPROVAL_POLICY_V1,
        StrategyFamily.RAW_RECORDED_APPROVAL,
        StrategyFamily.NO_TRADE,
    }
    return tuple(
        StrategyFamilyDefinition(
            family=family,
            description=description,
            interpretable=True,
            benchmark=family in benchmarks,
        )
        for family, description in descriptions.items()
    )


__all__ = ["StrategyFamilyDefinition", "StrategyFamilyRegistry"]
