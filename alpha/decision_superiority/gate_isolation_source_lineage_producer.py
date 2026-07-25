"""Immutable source-lineage producer for DSI-002A frozen input capture."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    _normalise,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)

SOURCE_LINEAGE_PRODUCER_VERSION = "DSI-002A-source-lineage-v1"


@dataclass(frozen=True, slots=True)
class SourceLineageCaptureInput:
    """Immutable provider, artifact, and path lineage for one candidate."""

    artifact_hashes: Mapping[str, str]
    provider_versions: Mapping[str, str]
    source_paths: Mapping[str, str]
    dataset_versions: Mapping[str, str]
    observed_on: str

    def __post_init__(self) -> None:
        if not self.artifact_hashes:
            raise ValueError("artifact_hashes cannot be empty")
        if not self.provider_versions:
            raise ValueError("provider_versions cannot be empty")
        if not self.source_paths:
            raise ValueError("source_paths cannot be empty")
        if not self.dataset_versions:
            raise ValueError("dataset_versions cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")
        for name, values in (
            ("artifact_hashes", self.artifact_hashes),
            ("provider_versions", self.provider_versions),
            ("source_paths", self.source_paths),
            ("dataset_versions", self.dataset_versions),
        ):
            if any(
                not key.strip() or not value.strip()
                for key, value in values.items()
            ):
                raise ValueError(f"{name} keys and values cannot be empty")


class SourceLineageSnapshotProducer:
    """Produce canonical source lineage without altering source objects."""

    def produce(
        self,
        capture_input: SourceLineageCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a deterministic source-lineage section snapshot."""

        payload = {
            "artifact_hashes": _normalise(capture_input.artifact_hashes),
            "dataset_versions": _normalise(capture_input.dataset_versions),
            "provider_versions": _normalise(capture_input.provider_versions),
            "source_paths": _normalise(capture_input.source_paths),
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.SOURCE_LINEAGE,
            payload=payload,
            source_version=SOURCE_LINEAGE_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


__all__ = [
    "SOURCE_LINEAGE_PRODUCER_VERSION",
    "SourceLineageCaptureInput",
    "SourceLineageSnapshotProducer",
]
