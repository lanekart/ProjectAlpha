from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alpha.backtest.backtest_export_session import BacktestExportSession


@dataclass(frozen=True, slots=True)
class BacktestExportArtifact:
    """Immutable descriptor for one persisted backtest export artifact."""

    kind: str
    path: Path

    def __post_init__(self) -> None:
        normalized_kind = self.kind.strip().lower()
        if not normalized_kind:
            raise ValueError("artifact kind cannot be empty")
        if not self.path.name:
            raise ValueError("artifact path cannot be empty")

        object.__setattr__(self, "kind", normalized_kind)

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": str(self.path),
        }


@dataclass(frozen=True, slots=True)
class BacktestExportManifest:
    """Immutable machine-readable inventory of backtest export artifacts."""

    artifacts: tuple[BacktestExportArtifact, ...]
    session: BacktestExportSession | None = None

    def __init__(
        self,
        artifacts: Iterable[BacktestExportArtifact],
        *,
        session: BacktestExportSession | None = None,
    ) -> None:
        ordered_artifacts = tuple(
            sorted(
                artifacts,
                key=lambda artifact: (artifact.kind, str(artifact.path)),
            )
        )
        object.__setattr__(self, "artifacts", ordered_artifacts)
        object.__setattr__(self, "session", session)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def is_empty(self) -> bool:
        return not self.artifacts

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
        }

        if self.session is not None:
            payload["session"] = self.session.as_dict()

        return payload

    def as_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.as_dict(),
            indent=indent,
            sort_keys=True,
        )
