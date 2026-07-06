"""Weighted multi-objective evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from alpha.optimization.objective import Objective
from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class WeightedObjectiveComponent:
    """One objective with its scalar weight."""

    objective: Objective
    weight: Decimal

    def __post_init__(self) -> None:
        if self.weight == Decimal("0"):
            raise ValueError("objective weight cannot be zero")


@dataclass(frozen=True, slots=True)
class WeightedObjective:
    """Composable weighted portfolio objective."""

    components: tuple[WeightedObjectiveComponent, ...]
    name: str = "weighted_objective"

    def __post_init__(self) -> None:
        if len(self.components) == 0:
            raise ValueError("weighted objective requires at least one component")
        if not self.name.strip():
            raise ValueError("weighted objective name cannot be empty")

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        """Evaluate weighted score across all objective components."""

        raw_components: dict[str, Decimal] = {}
        weighted_components: dict[str, Decimal] = {}
        total_score = Decimal("0")

        for component in self.components:
            result = component.objective.evaluate(
                optimization_input=optimization_input,
                target_weights=target_weights,
            )
            weighted_score = result.score * component.weight
            raw_components[result.name] = result.score
            weighted_components[f"{result.name}.weighted"] = weighted_score
            total_score += weighted_score

        return ObjectiveResult(
            name=self.name,
            score=total_score,
            components={**raw_components, **weighted_components},
            metadata={"component_count": Decimal(len(self.components))},
        )
