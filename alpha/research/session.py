"""Research session aggregate model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from alpha.research.persistence import (
    ResearchExperimentManifest,
    ResearchExperimentRecord,
)

SessionMetadataValue = bool | int | str | Decimal


@dataclass(frozen=True, slots=True)
class ResearchSessionEntry:
    """Immutable entry linking a named research run into a session."""

    label: str
    manifest: ResearchExperimentManifest
    strategy_name: str = "default"
    notes: str = ""
    metadata: Mapping[str, SessionMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_label = self.label.strip()
        normalized_strategy_name = self.strategy_name.strip()
        normalized_notes = self.notes.strip()

        if not normalized_label:
            raise ValueError("session entry label cannot be empty")
        if not normalized_strategy_name:
            raise ValueError("strategy_name cannot be empty")

        copied_metadata: dict[str, SessionMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("session entry metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "label", normalized_label)
        object.__setattr__(self, "strategy_name", normalized_strategy_name)
        object.__setattr__(self, "notes", normalized_notes)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @property
    def run_id(self) -> str:
        """Return the underlying experiment run id."""

        return self.manifest.run_id

    @property
    def objective_metric(self) -> str:
        """Return the underlying manifest objective metric."""

        return self.manifest.objective_metric

    @property
    def best_record(self) -> ResearchExperimentRecord:
        """Return the best persisted record for this entry."""

        return self.manifest.best_record

    @property
    def best_objective_value(self) -> Decimal:
        """Return the best objective value for this entry."""

        return self.best_record.objective_value


@dataclass(frozen=True, slots=True)
class ResearchSessionSummary:
    """Immutable summary of a research session."""

    session_id: str
    name: str
    entry_count: int
    objective_metrics: tuple[str, ...]
    best_entry: ResearchSessionEntry
    metadata: Mapping[str, SessionMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_session_id = self.session_id.strip()
        normalized_name = self.name.strip()

        if not normalized_session_id:
            raise ValueError("session_id cannot be empty")
        if not normalized_name:
            raise ValueError("session summary name cannot be empty")
        if self.entry_count <= 0:
            raise ValueError("entry_count must be positive")
        if len(self.objective_metrics) == 0:
            raise ValueError("session summary requires at least one objective metric")

        normalized_metrics = tuple(
            metric.strip() for metric in self.objective_metrics if metric.strip()
        )
        if len(normalized_metrics) != len(self.objective_metrics):
            raise ValueError("objective metric cannot be empty")

        copied_metadata: dict[str, SessionMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_key = name.strip()
            if not normalized_key:
                raise ValueError("summary metadata name cannot be empty")
            copied_metadata[normalized_key] = value

        sorted_metrics = tuple(sorted(set(normalized_metrics)))

        object.__setattr__(self, "session_id", normalized_session_id)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "objective_metrics", sorted_metrics)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))


@dataclass(frozen=True, slots=True)
class ResearchSession:
    """Immutable aggregate of related research experiment manifests."""

    session_id: str
    name: str
    entries: tuple[ResearchSessionEntry, ...]
    description: str = ""
    metadata: Mapping[str, SessionMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_session_id = self.session_id.strip()
        normalized_name = self.name.strip()
        normalized_description = self.description.strip()

        if not normalized_session_id:
            raise ValueError("session_id cannot be empty")
        if not normalized_name:
            raise ValueError("research session name cannot be empty")
        if len(self.entries) == 0:
            raise ValueError("research session requires at least one entry")

        labels = tuple(entry.label for entry in self.entries)
        if len(set(labels)) != len(labels):
            raise ValueError("research session cannot contain duplicate labels")

        run_ids = tuple(entry.run_id for entry in self.entries)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("research session cannot contain duplicate run ids")

        copied_metadata: dict[str, SessionMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_key = name.strip()
            if not normalized_key:
                raise ValueError("session metadata name cannot be empty")
            copied_metadata[normalized_key] = value

        object.__setattr__(self, "session_id", normalized_session_id)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "description", normalized_description)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @property
    def entry_count(self) -> int:
        """Return number of entries in the session."""

        return len(self.entries)

    @property
    def objective_metrics(self) -> tuple[str, ...]:
        """Return sorted objective metrics represented in the session."""

        return tuple(sorted({entry.objective_metric for entry in self.entries}))

    @property
    def best_entry(self) -> ResearchSessionEntry:
        """Return the best entry by objective value, then deterministic label."""

        return max(
            self.entries,
            key=lambda entry: (
                entry.best_objective_value,
                _reverse_sort_key(entry.label),
            ),
        )

    @property
    def best_record(self) -> ResearchExperimentRecord:
        """Return the best persisted record across the session."""

        return self.best_entry.best_record

    def summary(self) -> ResearchSessionSummary:
        """Return an immutable summary for the session."""

        return ResearchSessionSummary(
            session_id=self.session_id,
            name=self.name,
            entry_count=self.entry_count,
            objective_metrics=self.objective_metrics,
            best_entry=self.best_entry,
            metadata=self.metadata,
        )

    def with_entry(self, entry: ResearchSessionEntry) -> ResearchSession:
        """Return a new session with one additional entry."""

        return ResearchSession(
            session_id=self.session_id,
            name=self.name,
            entries=(*self.entries, entry),
            description=self.description,
            metadata=self.metadata,
        )

    def entry_for_label(self, label: str) -> ResearchSessionEntry:
        """Return an entry by label."""

        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("label cannot be empty")

        for entry in self.entries:
            if entry.label == normalized_label:
                return entry

        raise KeyError(f"unknown research session label: {normalized_label}")

    def entry_for_run_id(self, run_id: str) -> ResearchSessionEntry:
        """Return an entry by persisted run id."""

        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id cannot be empty")

        for entry in self.entries:
            if entry.run_id == normalized_run_id:
                return entry

        raise KeyError(f"unknown research session run id: {normalized_run_id}")

    def entries_for_strategy(
        self,
        strategy_name: str,
    ) -> tuple[ResearchSessionEntry, ...]:
        """Return entries matching a strategy name in deterministic session order."""

        normalized_strategy_name = strategy_name.strip()
        if not normalized_strategy_name:
            raise ValueError("strategy_name cannot be empty")

        return tuple(
            entry
            for entry in self.entries
            if entry.strategy_name == normalized_strategy_name
        )


@dataclass(frozen=True, slots=True)
class ResearchSessionBuilder:
    """Deterministic factory for research session aggregates."""

    session_id: str
    name: str
    description: str = ""
    metadata: Mapping[str, SessionMetadataValue] = field(default_factory=dict)

    def build(
        self,
        entries: tuple[ResearchSessionEntry, ...],
    ) -> ResearchSession:
        """Build a research session from entries."""

        return ResearchSession(
            session_id=self.session_id,
            name=self.name,
            entries=entries,
            description=self.description,
            metadata=self.metadata,
        )

    def build_from_manifests(
        self,
        manifests: Mapping[str, ResearchExperimentManifest],
        *,
        strategy_name: str = "default",
        metadata: Mapping[str, SessionMetadataValue] | None = None,
    ) -> ResearchSession:
        """Build a session from label-to-manifest mappings."""

        entries = tuple(
            ResearchSessionEntry(
                label=label,
                manifest=manifest,
                strategy_name=strategy_name,
                metadata={} if metadata is None else metadata,
            )
            for label, manifest in manifests.items()
        )
        return self.build(entries)


def _reverse_sort_key(value: str) -> tuple[int, ...]:
    """Return a deterministic reverse lexical key for max tie-breaking."""

    return tuple(-ord(character) for character in value)


__all__ = [
    "ResearchSession",
    "ResearchSessionBuilder",
    "ResearchSessionEntry",
    "ResearchSessionSummary",
    "SessionMetadataValue",
]
