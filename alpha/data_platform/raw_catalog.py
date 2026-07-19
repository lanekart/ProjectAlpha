from __future__ import annotations

from hashlib import sha256

from alpha.data_platform.dataset_registry import DatasetRegistry
from alpha.data_platform.models import RawArtifactMetadata, stable_hash


class RawArtifactCatalog:
    """Append-only metadata catalog for immutable source bytes."""

    def __init__(
        self,
        registry: DatasetRegistry,
        artifacts: tuple[RawArtifactMetadata, ...] = (),
    ) -> None:
        ordered = tuple(sorted(artifacts, key=lambda item: item.artifact_id))
        if len({item.artifact_id for item in ordered}) != len(ordered):
            raise ValueError("ADP raw artifact ids must be unique")
        for artifact in ordered:
            registry.get(artifact.dataset_id)
        self._registry = registry
        self._artifacts = ordered

    @property
    def artifacts(self) -> tuple[RawArtifactMetadata, ...]:
        return self._artifacts

    @property
    def catalog_hash(self) -> str:
        return stable_hash(self._artifacts)

    def append(self, artifact: RawArtifactMetadata) -> RawArtifactCatalog:
        self._registry.get(artifact.dataset_id)
        existing = {item.artifact_id: item for item in self._artifacts}
        if artifact.artifact_id in existing:
            if existing[artifact.artifact_id] == artifact:
                return self
            raise ValueError("ADP raw artifacts cannot be modified in place")
        if any(
            item.relative_path == artifact.relative_path for item in self._artifacts
        ):
            raise ValueError("ADP raw artifact paths cannot be reused")
        return RawArtifactCatalog(self._registry, (*self._artifacts, artifact))

    @staticmethod
    def verify_bytes(artifact: RawArtifactMetadata, payload: bytes) -> bool:
        return sha256(payload).hexdigest() == artifact.checksum


__all__ = ["RawArtifactCatalog"]
