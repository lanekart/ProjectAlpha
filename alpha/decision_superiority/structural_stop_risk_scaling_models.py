"""Typed research-only contracts for DSI-012 structural-stop risk scaling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI012_CONTRACT_VERSION = "DSI-012-v1.0.0"
DSI012_RESEARCH_SCOPE = "GOVERNED_STRUCTURAL_STOP_RISK_SCALING_RESEARCH"
DSI012_MECHANISM_ID = "STOP-STRUCTURAL-10D"


class StructuralStopRiskScalingError(ValueError):
    """Raised when the governed DSI-012 contract cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class StructuralStopRiskScalingPolicy:
    """Pre-registered target, leverage, financing, and capacity assumptions."""

    risk_multiplier: float = 1.50
    base_financing_rate: float = 0.12
    stress_financing_rate: float = 0.18
    sessions_per_year: int = 252
    minimum_net_cagr: float = 0.25
    maximum_drawdown_floor: float = -0.12
    minimum_calmar: float = 2.0
    minimum_profit_factor: float = 1.5
    minimum_excess_cagr: float = 0.05
    maximum_gross_exposure: float = 1.25
    maximum_position_fraction: float = 0.25
    capacity_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if abs(self.risk_multiplier - 1.50) > 1e-12:
            raise StructuralStopRiskScalingError("DSI012_RISK_MULTIPLIER_NOT_FROZEN")
        if not 0 <= self.base_financing_rate < self.stress_financing_rate < 1:
            raise StructuralStopRiskScalingError("DSI012_FINANCING_ASSUMPTIONS_INVALID")
        if self.sessions_per_year < 1:
            raise StructuralStopRiskScalingError("DSI012_SESSIONS_PER_YEAR_INVALID")
        if self.minimum_net_cagr <= 0:
            raise StructuralStopRiskScalingError("DSI012_CAGR_TARGET_INVALID")
        if not -1 < self.maximum_drawdown_floor < 0:
            raise StructuralStopRiskScalingError("DSI012_DRAWDOWN_FLOOR_INVALID")
        if self.minimum_calmar <= 0 or self.minimum_profit_factor <= 0:
            raise StructuralStopRiskScalingError("DSI012_RISK_RETURN_TARGET_INVALID")
        if not 1 < self.maximum_gross_exposure <= 2:
            raise StructuralStopRiskScalingError("DSI012_GROSS_EXPOSURE_LIMIT_INVALID")
        if not 0 < self.maximum_position_fraction <= 1:
            raise StructuralStopRiskScalingError("DSI012_POSITION_LIMIT_INVALID")
        if not 0 < self.capacity_multiplier <= 1:
            raise StructuralStopRiskScalingError("DSI012_CAPACITY_MULTIPLIER_INVALID")


@dataclass(frozen=True, slots=True)
class StructuralStopRiskScalingSourcePaths:
    """Caller-selected immutable source chain for DSI-012."""

    dsi009_certificate: Path
    dsi008_certificate: Path
    dsi007_certificate: Path
    database: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class StructuralStopRiskScalingResult:
    """Deterministic DSI-012 evidence, metrics, and decision."""

    source_commit: str
    readiness: str
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )


__all__ = [
    "DSI012_CONTRACT_VERSION",
    "DSI012_MECHANISM_ID",
    "DSI012_RESEARCH_SCOPE",
    "StructuralStopRiskScalingError",
    "StructuralStopRiskScalingPolicy",
    "StructuralStopRiskScalingResult",
    "StructuralStopRiskScalingSourcePaths",
]
