"""Typed contracts for DSI-010 pre-2016 external-era validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI010_CONTRACT_VERSION = "DSI-010-v1.0.0"
DSI010_RESEARCH_SCOPE = "GOVERNED_PRE2016_EXTERNAL_ERA_VALIDATION"
DSI010_EXTERNAL_START = date(2005, 1, 1)
DSI010_EXTERNAL_END = date(2015, 12, 31)
DSI010_FROZEN_CHALLENGER_ID = "STOP-STRUCTURAL-10D"


class Pre2016ExternalValidationError(ValueError):
    """Raised when DSI-010 cannot satisfy its governed contract."""


class ExternalValidationClassification(StrEnum):
    """Final external-era interpretation."""

    PASSED = "EXTERNAL_VALIDATION_PASSED"
    DIRECTIONALLY_SUPPORTED = "EXTERNAL_VALIDATION_DIRECTIONALLY_SUPPORTED"
    MIXED = "EXTERNAL_VALIDATION_MIXED"
    FAILED = "EXTERNAL_VALIDATION_FAILED"
    BEATS_INCUMBENT_NOT_BENCHMARK = "CHALLENGER_BEATS_INCUMBENT_NOT_BENCHMARK"
    BEATS_BENCHMARK = "CHALLENGER_BEATS_BENCHMARK"
    HIGH_CONCENTRATION = "CHALLENGER_HIGH_CONCENTRATION"
    REGIME_DEPENDENT = "CHALLENGER_REGIME_DEPENDENT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_EXTERNAL_SAMPLE"


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationPolicy:
    """Immutable external-era protocol signed before result inspection."""

    external_start: date = DSI010_EXTERNAL_START
    external_end: date = DSI010_EXTERNAL_END
    frozen_challenger_id: str = DSI010_FROZEN_CHALLENGER_ID
    primary_benchmark_name: str = "NIFTY_500_TRI"
    secondary_benchmark_name: str = "NIFTY_50_TRI"
    minimum_external_trades: int = 30
    maximum_top_five_profit_share: float = 0.70
    transaction_cost_fraction: float = 0.002
    slippage_fraction: float = 0.001
    allow_partial_market_coverage: bool = True

    def __post_init__(self) -> None:
        if self.external_end < self.external_start:
            raise Pre2016ExternalValidationError("EXTERNAL_END_PRECEDES_EXTERNAL_START")
        if self.external_end >= date(2016, 1, 1):
            raise Pre2016ExternalValidationError("PRE2016_HOLDOUT_OVERLAPS_2016")
        if self.frozen_challenger_id != DSI010_FROZEN_CHALLENGER_ID:
            raise Pre2016ExternalValidationError("FROZEN_CHALLENGER_ID_DRIFT")
        if self.minimum_external_trades < 1:
            raise Pre2016ExternalValidationError(
                "MINIMUM_EXTERNAL_TRADES_MUST_BE_POSITIVE"
            )
        if not 0 < self.maximum_top_five_profit_share <= 1:
            raise Pre2016ExternalValidationError(
                "MAXIMUM_TOP_FIVE_PROFIT_SHARE_INVALID"
            )
        if self.transaction_cost_fraction < 0 or self.slippage_fraction < 0:
            raise Pre2016ExternalValidationError("COST_OR_SLIPPAGE_ASSUMPTION_INVALID")


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationSourcePaths:
    """Caller-selected immutable DSI-010 inputs."""

    dsi009_certificate: Path
    dsi007_certificate: Path
    database: Path
    historical_truth_snapshots: Path
    benchmark: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class Pre2016ExternalValidationResult:
    """Deterministic rows and conclusions for DSI-010."""

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
    "DSI010_EXTERNAL_END",
    "DSI010_EXTERNAL_START",
    "DSI010_FROZEN_CHALLENGER_ID",
    "DSI010_RESEARCH_SCOPE",
    "ExternalValidationClassification",
    "Pre2016ExternalValidationError",
    "Pre2016ExternalValidationPolicy",
    "Pre2016ExternalValidationResult",
    "Pre2016ExternalValidationSourcePaths",
]
