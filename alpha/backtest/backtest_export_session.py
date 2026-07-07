from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

_DEFAULT_FORMAT_VERSION = "1.0"
_DEFAULT_GENERATOR = "project-alpha"


@dataclass(frozen=True, slots=True)
class BacktestExportSession:
    """Immutable deterministic metadata for a backtest export session."""

    strategy: str
    start: str
    end: str
    format_version: str = _DEFAULT_FORMAT_VERSION
    generator: str = _DEFAULT_GENERATOR

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        normalized_start = self.start.strip()
        normalized_end = self.end.strip()
        normalized_format_version = self.format_version.strip()
        normalized_generator = self.generator.strip().lower()

        if not normalized_strategy:
            raise ValueError("strategy cannot be empty")
        if not normalized_start:
            raise ValueError("start cannot be empty")
        if not normalized_end:
            raise ValueError("end cannot be empty")
        if not normalized_format_version:
            raise ValueError("format_version cannot be empty")
        if not normalized_generator:
            raise ValueError("generator cannot be empty")

        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(self, "start", normalized_start)
        object.__setattr__(self, "end", normalized_end)
        object.__setattr__(self, "format_version", normalized_format_version)
        object.__setattr__(self, "generator", normalized_generator)

    @property
    def session_id(self) -> str:
        payload = "|".join(
            (
                self.generator,
                self.format_version,
                self.strategy,
                self.start,
                self.end,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "generator": self.generator,
            "format_version": self.format_version,
            "strategy": self.strategy,
            "start": self.start,
            "end": self.end,
        }

    def as_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.as_dict(),
            indent=indent,
            sort_keys=True,
        )
