from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductArtifact:
    """Immutable description of a generated product artifact."""

    kind: str
    path: Path

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower()
        if not kind:
            raise ValueError("artifact kind cannot be empty")
        if self.path.name.strip() == "":
            raise ValueError("artifact path cannot be empty")

        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class ProductExportManifest:
    """Deterministic manifest of product report artifacts."""

    artifacts: tuple[ProductArtifact, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.artifacts,
                key=lambda artifact: (artifact.kind, artifact.path.as_posix()),
            )
        )
        object.__setattr__(self, "artifacts", ordered)

    @property
    def is_empty(self) -> bool:
        return len(self.artifacts) == 0

    def as_lines(self) -> tuple[str, ...]:
        if self.is_empty:
            return ("No product artifacts written.",)

        return tuple(
            f"{artifact.kind}: {artifact.path.as_posix()}"
            for artifact in self.artifacts
        )


__all__ = ["ProductArtifact", "ProductExportManifest"]
