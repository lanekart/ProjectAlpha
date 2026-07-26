"""Typed contracts for DSI-010 pre-2016 external-era validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI010_CONTRACT_VERSION = "DSI-010-v1.0.0"
DSI010_RESEARCH_SCOPE = "GOVERNED_PRE2016_EXTERNAL_VALIDATION"


class Pre2016ExternalValidationError(ValueError):
    """Raised when a DSI-010 governed boundary cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationPolicy:
    """Immutable external-era protocol frozen before result evaluation."""

    external_start: str = "2005-01-01"
    external_end: str = "2015-12-31"
    frozen_challenger_id: str = "STOP-STRUCTURAL-10D"
    primary_benchmark: str = "NIFTY_500_TRI"
    secondary_benchmark: str = "NIFTY_50_TRI"
    starting_capital: float = 1_000_000.0
    maximum_positions: int = 5
    transaction_cost_fraction: float = 0.002
    slippage_fraction: float = 0.001
    minimum_external_trades: int = 20

    def __post_init__(self) -> None:
        if self.external_start >= "2016-01-01" or self.external_end >= "2016-01-01":
            raise Pre2016ExternalValidationError("EXTERNAL_PERIOD_OVERLAPS_DISCOVERY_ERA")
        if self.external_end < self.external_start:
            raise Pre2016ExternalValidationError("EXTERNAL_PERIOD_INVALID")
        if self.frozen_challenger_id != "STOP-STRUCTURAL-10D":
            raise Pre2016ExternalValidationError("UNFROZEN_CHALLENGER_CONTRACT")
        if self.starting_capital <= 0 or self.maximum_positions < 1:
            raise Pre2016ExternalValidationError("PORTFOLIO_PROTOCOL_INVALID")
        if self.transaction_cost_fraction < 0 or self.slippage_fraction < 0:
            raise Pre2016ExternalValidationError("COST_PROTOCOL_INVALID")
        if self.minimum_external_trades < 1:
            raise Pre2016ExternalValidationError("MINIMUM_EXTERNAL_TRADES_INVALID")


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationSourcePaths:
    """Caller-selected immutable DSI-010 inputs."""

    dsi009_certificate: Path
    dsi007_certificate: Path
    database: Path
    historical_truth_snapshots: Path
    benchmark: str
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationResult:
    """Deterministic DSI-010 evidence and conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )


__all__ = [
    "DSI010_CONTRACT_VERSION",
    "DSI010_RESEARCH_SCOPE",
    "Pre2016ExternalValidationError",
    "Pre2016ExternalValidationPolicy",
    "Pre2016ExternalValidationResult",
    "Pre2016ExternalValidationSourcePaths",
]
