"""Deterministic research experiment persistence primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol

from alpha.research.parameter_sweep import (
    ParameterCombination,
    ParameterSweepReport,
    ParameterValue,
)

PersistedValue = bool | int | str | Decimal


@dataclass(frozen=True, slots=True)
class ResearchExperimentRecord:
    """Immutable persisted representation of one research experiment."""

    experiment_id: str
    parameters: Mapping[str, ParameterValue]
    objective_metric: str
    objective_value: Decimal
    rank: int
    metadata: Mapping[str, PersistedValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_experiment_id = self.experiment_id.strip()
        normalized_metric = self.objective_metric.strip()
        if not normalized_experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        if len(self.parameters) == 0:
            raise ValueError("experiment record requires at least one parameter")

        copied_parameters: dict[str, ParameterValue] = {}
        for name, value in self.parameters.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("parameter name cannot be empty")
            copied_parameters[normalized_name] = value

        copied_metadata: dict[str, PersistedValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "experiment_id", normalized_experiment_id)
        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "parameters", MappingProxyType(copied_parameters))
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @classmethod
    def from_sweep_result(
        cls,
        *,
        combination: ParameterCombination,
        objective_metric: str,
        objective_value: Decimal,
        rank: int,
        metadata: Mapping[str, PersistedValue] | None = None,
    ) -> ResearchExperimentRecord:
        """Build a persisted record from a parameter sweep result."""

        return cls(
            experiment_id=combination.experiment_id,
            parameters=combination.values,
            objective_metric=objective_metric,
            objective_value=objective_value,
            rank=rank,
            metadata={} if metadata is None else metadata,
        )


@dataclass(frozen=True, slots=True)
class ResearchExperimentManifest:
    """Immutable manifest for a persisted experiment report."""

    run_id: str
    objective_metric: str
    records: tuple[ResearchExperimentRecord, ...]
    metadata: Mapping[str, PersistedValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_run_id = self.run_id.strip()
        normalized_metric = self.objective_metric.strip()
        if not normalized_run_id:
            raise ValueError("run_id cannot be empty")
        if not normalized_metric:
            raise ValueError("objective_metric cannot be empty")
        if len(self.records) == 0:
            raise ValueError("manifest requires at least one record")

        expected_ranks = tuple(range(1, len(self.records) + 1))
        actual_ranks = tuple(record.rank for record in self.records)
        if actual_ranks != expected_ranks:
            raise ValueError("manifest records must be ordered by contiguous rank")

        for record in self.records:
            if record.objective_metric != normalized_metric:
                raise ValueError("all records must use the manifest objective metric")

        copied_metadata: dict[str, PersistedValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "run_id", normalized_run_id)
        object.__setattr__(self, "objective_metric", normalized_metric)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @property
    def record_count(self) -> int:
        """Return number of persisted experiment records."""

        return len(self.records)

    @property
    def best_record(self) -> ResearchExperimentRecord:
        """Return first-ranked experiment record."""

        return self.records[0]


class ResearchExperimentRepository(Protocol):
    """Repository protocol for persisted research experiment manifests."""

    def save(self, manifest: ResearchExperimentManifest) -> None:
        """Persist a manifest."""

    def load(self, run_id: str) -> ResearchExperimentManifest:
        """Load a manifest by run id."""


@dataclass(slots=True)
class InMemoryResearchExperimentRepository:
    """Deterministic in-memory repository for tests and application composition."""

    _manifests: dict[str, ResearchExperimentManifest] = field(default_factory=dict)

    def save(self, manifest: ResearchExperimentManifest) -> None:
        """Persist a manifest in memory."""

        self._manifests[manifest.run_id] = manifest

    def load(self, run_id: str) -> ResearchExperimentManifest:
        """Load a manifest by run id."""

        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id cannot be empty")
        try:
            return self._manifests[normalized_run_id]
        except KeyError as exc:
            raise KeyError(f"unknown research experiment run: {normalized_run_id}") from exc

    def contains(self, run_id: str) -> bool:
        """Return whether a run id has been persisted."""

        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id cannot be empty")
        return normalized_run_id in self._manifests


@dataclass(frozen=True, slots=True)
class ResearchExperimentPersistenceService:
    """Persist parameter sweep reports as immutable experiment manifests."""

    repository: ResearchExperimentRepository

    def persist_parameter_sweep(
        self,
        *,
        run_id: str,
        report: ParameterSweepReport,
        metadata: Mapping[str, PersistedValue] | None = None,
    ) -> ResearchExperimentManifest:
        """Persist a parameter sweep report and return its manifest."""

        records = tuple(
            ResearchExperimentRecord.from_sweep_result(
                combination=result.combination,
                objective_metric=report.objective_metric,
                objective_value=result.objective_value,
                rank=rank,
            )
            for rank, result in enumerate(report.results, start=1)
        )
        manifest = ResearchExperimentManifest(
            run_id=run_id,
            objective_metric=report.objective_metric,
            records=records,
            metadata={} if metadata is None else metadata,
        )
        self.repository.save(manifest)
        return manifest
