from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from alpha.application.historical_ingestion import MarketAnalysisResult
from alpha.application.intelligence import IntelligenceRun


class RuntimeMode(StrEnum):
    """Supported runtime execution modes."""

    DEMO = "DEMO"
    LIVE = "LIVE"


class RuntimeStatus(StrEnum):
    """Deterministic status of a runtime execution."""

    SUCCESS = "SUCCESS"


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Immutable metadata describing one Project Alpha runtime execution."""

    requested_on: date
    observed_on: date
    mode: RuntimeMode
    started_at: datetime
    completed_at: datetime
    status: RuntimeStatus = RuntimeStatus.SUCCESS
    attributes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        started_at = _normalize_datetime(self.started_at)
        completed_at = _normalize_datetime(self.completed_at)

        if completed_at < started_at:
            raise ValueError("runtime completed_at cannot be before started_at")

        attributes = {
            key.strip(): value.strip()
            for key, value in self.attributes.items()
            if key.strip() and value.strip()
        }

        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(sorted(attributes.items()))),
        )

    @property
    def duration_seconds(self) -> str:
        """Return deterministic runtime duration in seconds."""

        duration = self.completed_at - self.started_at
        return f"{duration.total_seconds():.6f}"

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic machine-readable runtime metadata."""

        return {
            "requested_on": self.requested_on.isoformat(),
            "observed_on": self.observed_on.isoformat(),
            "mode": self.mode.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """
    Canonical immutable result for one Project Alpha runtime execution.

    The runtime wraps existing application outputs rather than replacing them.
    This preserves public contracts while creating one operational aggregate for
    CLI, schedulers, APIs, automation, and future interfaces.
    """

    metadata: RuntimeMetadata
    intelligence_run: IntelligenceRun
    market_analysis: MarketAnalysisResult | None = None

    @property
    def requested_on(self) -> date:
        """Return the user-requested date for the runtime execution."""

        return self.metadata.requested_on

    @property
    def observed_on(self) -> date:
        """Return the canonical observed market date used by downstream engines."""

        return self.metadata.observed_on

    @property
    def mode(self) -> RuntimeMode:
        """Return runtime execution mode."""

        return self.metadata.mode

    @property
    def status(self) -> RuntimeStatus:
        """Return runtime execution status."""

        return self.metadata.status

    @property
    def summary_lines(self) -> tuple[str, ...]:
        """Expose existing intelligence summary lines for backward compatibility."""

        return self.intelligence_run.summary_lines

    @property
    def workflow(self) -> str:
        """Return runtime workflow name."""

        return self.metadata.attributes.get("workflow", "unknown")

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic machine-readable runtime payload."""

        payload = self.intelligence_run.as_dict()
        payload["runtime"] = self.metadata.as_dict()

        if self.market_analysis is not None:
            payload["market_analysis"] = {
                "requested_on": self.market_analysis.requested_on.isoformat(),
                "observed_on": self.market_analysis.observed_on.isoformat(),
                "row_count": len(self.market_analysis.analysis),
            }

        return payload


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "RuntimeMetadata",
    "RuntimeMode",
    "RuntimeResult",
    "RuntimeStatus",
]
