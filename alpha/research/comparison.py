"""Deterministic strategy comparison research primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from alpha.research.parameter_sweep import ParameterValue
from alpha.research.session import ResearchSession, ResearchSessionEntry

ComparisonMetadataValue = bool | int | str | Decimal


@dataclass(frozen=True, slots=True)
class StrategyComparisonResult:
    """Immutable comparison result for one research session entry."""

    strategy_name: str
    label: str
    run_id: str
    objective_metric: str
    objective_value: Decimal
    source_rank: int
    comparison_rank: int
    parameters: Mapping[str, ParameterValue]
    metadata: Mapping[str, ComparisonMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_strategy_name = self.strategy_name.strip()
        normalized_label = self.label.strip()
        normalized_run_id = self.run_id.strip()
        normalized_metric = self.objective_metric.strip()

        if not normalized_strategy_name:
            raise ValueError("strategy_name cannot be empty")
        if not normalized_label:
            raise ValueError("label cannot be empty")
        if not normalized_run_id:
            raise ValueError("run_id cannot be empty")
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        if self.source_rank <= 0:
            raise ValueError("source_rank must be positive")
        if self.comparison_rank <= 0:
            raise ValueError("comparison_rank must be positive")
        if len(self.parameters) == 0:
            raise ValueError("strategy comparison result requires parameters")

        copied_parameters: dict[str, ParameterValue] = {}
        for name, value in self.parameters.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("parameter name cannot be empty")
            copied_parameters[normalized_name] = value

        copied_metadata: dict[str, ComparisonMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "strategy_name", normalized_strategy_name)
        object.__setattr__(self, "label", normalized_label)
        object.__setattr__(self, "run_id", normalized_run_id)
        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "parameters", MappingProxyType(copied_parameters))
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))


@dataclass(frozen=True, slots=True)
class StrategyComparisonReport:
    """Immutable aggregate comparison report across research strategies."""

    session_id: str
    results: tuple[StrategyComparisonResult, ...]
    objective_metric: str
    higher_is_better: bool = True
    metadata: Mapping[str, ComparisonMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_session_id = self.session_id.strip()
        normalized_metric = self.objective_metric.strip()

        if not normalized_session_id:
            raise ValueError("session_id cannot be empty")
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        if len(self.results) == 0:
            raise ValueError("strategy comparison report requires at least one result")

        expected_ranks = tuple(range(1, len(self.results) + 1))
        actual_ranks = tuple(result.comparison_rank for result in self.results)
        if actual_ranks != expected_ranks:
            raise ValueError("comparison results must be ordered by contiguous rank")

        for result in self.results:
            if result.objective_metric != normalized_metric:
                raise ValueError("all results must use the report objective metric")

        copied_metadata: dict[str, ComparisonMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "session_id", normalized_session_id)
        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @property
    def result_count(self) -> int:
        """Return number of compared strategy results."""

        return len(self.results)

    @property
    def strategy_count(self) -> int:
        """Return number of unique strategy names in the report."""

        return len({result.strategy_name for result in self.results})

    @property
    def best_result(self) -> StrategyComparisonResult:
        """Return the first-ranked comparison result."""

        return self.results[0]

    def results_for_strategy(
        self,
        strategy_name: str,
    ) -> tuple[StrategyComparisonResult, ...]:
        """Return comparison results for a strategy name."""

        normalized_strategy_name = strategy_name.strip()
        if not normalized_strategy_name:
            raise ValueError("strategy_name cannot be empty")

        return tuple(
            result
            for result in self.results
            if result.strategy_name == normalized_strategy_name
        )

    def objective_values(self) -> Mapping[str, Decimal]:
        """Return objective values keyed by strategy label."""

        return MappingProxyType(
            {result.label: result.objective_value for result in self.results}
        )


@dataclass(frozen=True, slots=True)
class StrategyComparisonEngine:
    """Compare persisted research session entries by objective metric."""

    objective_metric: str
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        normalized_metric = self.objective_metric.strip()
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        object.__setattr__(self, "objective_metric", normalized_metric)

    def compare(
        self,
        *,
        session: ResearchSession,
        metadata: Mapping[str, ComparisonMetadataValue] | None = None,
    ) -> StrategyComparisonReport:
        """Compare all entries in a research session."""

        results = tuple(
            _result_from_entry(
                entry=entry,
                objective_metric=self.objective_metric,
                comparison_rank=index,
            )
            for index, entry in enumerate(
                _rank_entries(
                    entries=session.entries,
                    objective_metric=self.objective_metric,
                    higher_is_better=self.higher_is_better,
                ),
                start=1,
            )
        )

        return StrategyComparisonReport(
            session_id=session.session_id,
            results=results,
            objective_metric=self.objective_metric,
            higher_is_better=self.higher_is_better,
            metadata={} if metadata is None else metadata,
        )


def _rank_entries(
    *,
    entries: tuple[ResearchSessionEntry, ...],
    objective_metric: str,
    higher_is_better: bool,
) -> tuple[ResearchSessionEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                _entry_objective_value(entry=entry, objective_metric=objective_metric),
                entry.label,
                entry.manifest.run_id,
            ),
            reverse=higher_is_better,
        )
    )


def _result_from_entry(
    *,
    entry: ResearchSessionEntry,
    objective_metric: str,
    comparison_rank: int,
) -> StrategyComparisonResult:
    record = entry.manifest.best_record
    if entry.manifest.objective_metric != objective_metric:
        raise ValueError(
            "session entry objective metric does not match comparison objective metric"
        )
    if record.objective_metric != objective_metric:
        raise ValueError(
            "best record objective metric does not match comparison objective metric"
        )

    return StrategyComparisonResult(
        strategy_name=entry.strategy_name,
        label=entry.label,
        run_id=entry.manifest.run_id,
        objective_metric=objective_metric,
        objective_value=record.objective_value,
        source_rank=record.rank,
        comparison_rank=comparison_rank,
        parameters=record.parameters,
    )


def _entry_objective_value(
    *,
    entry: ResearchSessionEntry,
    objective_metric: str,
) -> Decimal:
    if entry.manifest.objective_metric != objective_metric:
        raise ValueError(
            "session entry objective metric does not match comparison objective metric"
        )
    return entry.manifest.best_record.objective_value
