"""Deterministic parameter sweep research primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product
from types import MappingProxyType
from typing import Any, Protocol

from alpha.research.walk_forward import WalkForwardReport

ParameterValue = bool | int | str | Decimal


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """Immutable definition for one sweep parameter."""

    name: str
    values: tuple[ParameterValue, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("parameter name cannot be empty")
        if len(self.values) == 0:
            raise ValueError("parameter definition requires at least one value")
        if len(set(self.values)) != len(self.values):
            raise ValueError("parameter definition cannot contain duplicate values")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ParameterCombination:
    """Immutable concrete parameter combination."""

    experiment_id: str
    values: Mapping[str, ParameterValue]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_experiment_id = self.experiment_id.strip()
        if not normalized_experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if len(self.values) == 0:
            raise ValueError("parameter combination requires at least one value")

        copied_values: dict[str, ParameterValue] = {}
        for name, value in self.values.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("parameter combination name cannot be empty")
            copied_values[normalized_name] = value

        object.__setattr__(self, "experiment_id", normalized_experiment_id)
        object.__setattr__(self, "values", MappingProxyType(copied_values))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ParameterGrid:
    """Immutable deterministic parameter grid."""

    parameters: tuple[ParameterDefinition, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.parameters) == 0:
            raise ValueError("parameter grid requires at least one parameter")

        names = tuple(parameter.name for parameter in self.parameters)
        if len(set(names)) != len(names):
            raise ValueError("parameter grid cannot contain duplicate parameter names")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def combinations(self) -> tuple[ParameterCombination, ...]:
        """Return deterministic Cartesian product combinations."""

        combinations: list[ParameterCombination] = []
        parameter_names = tuple(parameter.name for parameter in self.parameters)
        parameter_values = tuple(parameter.values for parameter in self.parameters)

        for index, values in enumerate(product(*parameter_values)):
            combination_values = dict(zip(parameter_names, values, strict=True))
            combinations.append(
                ParameterCombination(
                    experiment_id=_experiment_id(index=index, values=combination_values),
                    values=combination_values,
                )
            )

        return tuple(combinations)


@dataclass(frozen=True, slots=True)
class ParameterSweepResult:
    """Immutable result for one parameter combination."""

    combination: ParameterCombination
    report: WalkForwardReport
    objective_metric: str
    objective_value: Decimal
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_metric = self.objective_metric.strip()
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")

        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ParameterSweepReport:
    """Immutable aggregate parameter sweep report."""

    results: tuple[ParameterSweepResult, ...]
    objective_metric: str
    higher_is_better: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_metric = self.objective_metric.strip()
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        if len(self.results) == 0:
            raise ValueError("parameter sweep report requires at least one result")
        for result in self.results:
            if result.objective_metric != normalized_metric:
                raise ValueError("all sweep results must use the report objective metric")

        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def best_result(self) -> ParameterSweepResult:
        """Return the best-ranked parameter sweep result."""

        return self.results[0]

    @property
    def experiment_count(self) -> int:
        """Return number of evaluated combinations."""

        return len(self.results)


class ParameterSweepEvaluator(Protocol):
    """Protocol for evaluating one parameter combination."""

    def evaluate(self, combination: ParameterCombination) -> WalkForwardReport:
        """Evaluate a parameter combination and return a walk-forward report."""


@dataclass(frozen=True, slots=True)
class ParameterSweepEngine:
    """Strategy-agnostic deterministic parameter sweep engine."""

    objective_metric: str
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        normalized_metric = self.objective_metric.strip()
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        object.__setattr__(self, "objective_metric", normalized_metric)

    def run(
        self,
        *,
        grid: ParameterGrid,
        evaluator: ParameterSweepEvaluator,
        metadata: Mapping[str, Any] | None = None,
    ) -> ParameterSweepReport:
        """Evaluate each grid combination and return ranked report."""

        results: list[ParameterSweepResult] = []
        for combination in grid.combinations():
            report = evaluator.evaluate(combination)
            objective_value = report.average_metric(self.objective_metric)
            results.append(
                ParameterSweepResult(
                    combination=combination,
                    report=report,
                    objective_metric=self.objective_metric,
                    objective_value=objective_value,
                )
            )

        ranked_results = tuple(
            sorted(
                results,
                key=lambda result: (
                    result.objective_value,
                    result.combination.experiment_id,
                ),
                reverse=self.higher_is_better,
            )
        )
        return ParameterSweepReport(
            results=ranked_results,
            objective_metric=self.objective_metric,
            higher_is_better=self.higher_is_better,
            metadata={} if metadata is None else metadata,
        )


def _experiment_id(*, index: int, values: Mapping[str, ParameterValue]) -> str:
    encoded_values = "__".join(
        f"{name}-{_encode_value(value)}" for name, value in values.items()
    )
    return f"exp_{index:04d}__{encoded_values}"


def _encode_value(value: ParameterValue) -> str:
    return str(value).strip().replace(" ", "_").replace(".", "p").replace("-", "m")
