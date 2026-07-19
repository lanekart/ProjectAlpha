"""Development-only deterministic weight grid generation."""

from __future__ import annotations

import itertools
from dataclasses import replace
from decimal import Decimal

from alpha.tradingview_research.models import (
    ComponentWeight,
    LabConfiguration,
    ResearchPartition,
    WeightRange,
)


class WeightGridGenerator:
    """Generate bounded weight variants without touching validation or holdout."""

    def generate(
        self,
        baseline: LabConfiguration,
        ranges: tuple[WeightRange, ...],
        *,
        partition: ResearchPartition,
        maximum_variants: int = 5_000,
    ) -> tuple[LabConfiguration, ...]:
        if partition is not ResearchPartition.DEVELOPMENT:
            raise ValueError("weight search is allowed only on DEVELOPMENT")
        if not ranges:
            raise ValueError("at least one weight range is required")
        components = {item.component for item in baseline.weights}
        range_names = tuple(item.component for item in ranges)
        if len(range_names) != len(set(range_names)):
            raise ValueError("weight ranges must reference unique components")
        missing = sorted(set(range_names) - components)
        if missing:
            raise ValueError(f"unknown weight components: {', '.join(missing)}")
        values = tuple(self._values(item) for item in ranges)
        variant_count = 1
        for options in values:
            variant_count *= len(options)
        if variant_count > maximum_variants:
            raise ValueError(
                f"weight grid has {variant_count} variants; limit is {maximum_variants}"
            )
        variants: list[LabConfiguration] = []
        for combination in itertools.product(*values):
            replacements = dict(zip(range_names, combination, strict=True))
            weights = tuple(
                ComponentWeight(
                    component=item.component,
                    weight=replacements.get(item.component, item.weight),
                )
                for item in baseline.weights
            )
            variants.append(
                replace(
                    baseline,
                    name=f"TRL_WEIGHT_GRID_{len(variants) + 1:04d}",
                    weights=weights,
                )
            )
        return tuple(variants)

    def _values(self, range_: WeightRange) -> tuple[Decimal, ...]:
        values: list[Decimal] = []
        current = range_.minimum
        while current <= range_.maximum:
            values.append(current)
            current += range_.step
        return tuple(values)
