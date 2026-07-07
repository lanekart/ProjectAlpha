from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_ALLOWED_SUFFIXES = frozenset({".json", ".txt"})


@dataclass(frozen=True, slots=True)
class BacktestReportArtifactName:
    """Immutable deterministic artifact name for exported backtest reports."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("artifact name cannot be empty")
        if "/" in self.value or "\\" in self.value:
            raise ValueError("artifact name cannot contain path separators")


@dataclass(frozen=True, slots=True)
class BacktestReportArtifactNamer:
    """Build deterministic file names for backtest report artifacts."""

    prefix: str = "backtest"

    def __post_init__(self) -> None:
        normalized_prefix = self._slug(self.prefix)
        if not normalized_prefix:
            raise ValueError("prefix cannot be empty")
        object.__setattr__(self, "prefix", normalized_prefix)

    def name(
        self,
        *,
        strategy: str,
        start: date,
        end: date,
        suffix: str,
    ) -> BacktestReportArtifactName:
        normalized_suffix = suffix.lower()
        if normalized_suffix not in _ALLOWED_SUFFIXES:
            raise ValueError("unsupported artifact suffix")

        strategy_slug = self._slug(strategy)
        if not strategy_slug:
            raise ValueError("strategy cannot be empty")

        if end < start:
            raise ValueError("end date must be on or after start date")

        return BacktestReportArtifactName(
            value=(
                f"{self.prefix}_{strategy_slug}_"
                f"{start.isoformat()}_{end.isoformat()}{normalized_suffix}"
            )
        )

    def _slug(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        normalized = normalized.strip("_")
        return re.sub(r"_+", "_", normalized)
