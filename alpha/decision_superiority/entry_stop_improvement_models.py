"""Typed research-only contracts for DSI-009 entry and stop research."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI009_CONTRACT_VERSION = "DSI-009-v1.0.0"
DSI009_RESEARCH_SCOPE = "GOVERNED_ENTRY_STOP_IMPROVEMENT_RESEARCH"


class EntryStopImprovementError(ValueError):
    """Raised when a governed DSI-009 contract cannot be satisfied."""


class FillState(StrEnum):
    """Executable disposition of one signal under one entry rule."""

    ENTERED = "ENTERED"
    TRIGGER_NEVER_REACHED = "TRIGGER_NEVER_REACHED"
    INVALIDATED_BEFORE_ENTRY = "INVALIDATED_BEFORE_ENTRY"
    GAP_BEYOND_ENTRY_LIMIT = "GAP_BEYOND_ENTRY_LIMIT"
    LIQUIDITY_REJECTED = "LIQUIDITY_REJECTED"
    CAPITAL_UNAVAILABLE = "CAPITAL_UNAVAILABLE"
    REGIME_CHANGED_BEFORE_ENTRY = "REGIME_CHANGED_BEFORE_ENTRY"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class EntryChallengerState(StrEnum):
    """Governed entry challenger result."""

    REJECTED = "ENTRY_CHALLENGER_REJECTED"
    DESCRIPTIVELY_BETTER = "ENTRY_CHALLENGER_DESCRIPTIVELY_BETTER"
    DIRECTIONALLY_STABLE = "ENTRY_CHALLENGER_DIRECTIONALLY_STABLE"
    ROBUSTLY_BETTER = "ENTRY_CHALLENGER_ROBUSTLY_BETTER"
    INSUFFICIENT_SAMPLE = "ENTRY_CHALLENGER_INSUFFICIENT_SAMPLE"
    OVERFIT = "ENTRY_CHALLENGER_OVERFIT"
    NONEXECUTABLE = "ENTRY_CHALLENGER_NONEXECUTABLE"


class StopChallengerState(StrEnum):
    """Governed stop challenger result."""

    REJECTED = "STOP_CHALLENGER_REJECTED"
    DESCRIPTIVELY_BETTER = "STOP_CHALLENGER_DESCRIPTIVELY_BETTER"
    DIRECTIONALLY_STABLE = "STOP_CHALLENGER_DIRECTIONALLY_STABLE"
    ROBUSTLY_BETTER = "STOP_CHALLENGER_ROBUSTLY_BETTER"
    INSUFFICIENT_SAMPLE = "STOP_CHALLENGER_INSUFFICIENT_SAMPLE"
    OVERFIT = "STOP_CHALLENGER_OVERFIT"
    NONEXECUTABLE = "STOP_CHALLENGER_NONEXECUTABLE"


class EntryStopAttribution(StrEnum):
    """Mutually exclusive primary trade-path attribution."""

    THESIS_FAILED_AND_CONTINUED_LOWER = "THESIS_FAILED_AND_CONTINUED_LOWER"
    THESIS_FAILED_WITHOUT_RECOVERY = "THESIS_FAILED_WITHOUT_RECOVERY"
    ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP = "ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP"
    ENTRY_TOO_EXTENDED = "ENTRY_TOO_EXTENDED"
    STOP_TOO_TIGHT_RECOVERED_QUICKLY = "STOP_TOO_TIGHT_RECOVERED_QUICKLY"
    STOP_PREVENTED_LARGER_LOSS = "STOP_PREVENTED_LARGER_LOSS"
    ENTRY_AND_STOP_INTERACTION = "ENTRY_AND_STOP_INTERACTION"
    REGIME_TRANSITION_FAILURE = "REGIME_TRANSITION_FAILURE"
    UNFILLED_BETTER_ENTRY_AVAILABLE = "UNFILLED_BETTER_ENTRY_AVAILABLE"
    WINNER_ENTERED_WELL = "WINNER_ENTERED_WELL"
    WINNER_SURVIVED_ADVERSE_EXCURSION = "WINNER_SURVIVED_ADVERSE_EXCURSION"
    AMBIGUOUS = "AMBIGUOUS"


class StopValueState(StrEnum):
    """Mechanical value classification for an incumbent stop."""

    CREATED_VALUE = "STOP_CREATED_VALUE"
    PREVENTED_TAIL_LOSS = "STOP_PREVENTED_TAIL_LOSS"
    REDUCED_DRAWDOWN = "STOP_REDUCED_DRAWDOWN"
    DESTROYED_RECOVERABLE_TRADE = "STOP_DESTROYED_RECOVERABLE_TRADE"
    TOO_TIGHT = "STOP_TOO_TIGHT"
    TOO_WIDE = "STOP_TOO_WIDE"
    AMBIGUOUS = "STOP_EFFECT_AMBIGUOUS"
    NOT_TRIGGERED = "STOP_NOT_TRIGGERED"


@dataclass(frozen=True, slots=True)
class EntryMechanism:
    """One bounded and executable entry rule."""

    mechanism_id: str
    family: str
    trigger: str
    fill_convention: str
    maximum_wait_sessions: int
    gap_limit: float | None
    atr_offset: float | None
    maximum_extension_atr: float | None
    supported_regimes: tuple[str, ...]
    supported_strategies: tuple[str, ...]
    parameter_count: int
    complexity_score: int
    incumbent: bool = False

    def __post_init__(self) -> None:
        if not self.mechanism_id.strip():
            raise EntryStopImprovementError("entry mechanism ID is required")
        if self.maximum_wait_sessions < 1:
            raise EntryStopImprovementError("entry wait must be positive")
        if self.parameter_count < 0 or self.parameter_count > 2:
            raise EntryStopImprovementError("entry parameter search is unbounded")
        if self.complexity_score < 0:
            raise EntryStopImprovementError("entry complexity cannot be negative")


@dataclass(frozen=True, slots=True)
class StopMechanism:
    """One bounded stop rule evaluated after entry is frozen."""

    mechanism_id: str
    family: str
    atr_multiple: float | None
    maximum_risk_fraction: float | None
    structural_lookback: int | None
    activation_delay_sessions: int
    close_confirmation: bool
    parameter_count: int
    complexity_score: int
    incumbent: bool = False

    def __post_init__(self) -> None:
        if not self.mechanism_id.strip():
            raise EntryStopImprovementError("stop mechanism ID is required")
        if self.atr_multiple is not None and self.atr_multiple <= 0:
            raise EntryStopImprovementError("ATR stop multiple must be positive")
        if self.maximum_risk_fraction is not None and not (
            0 < self.maximum_risk_fraction < 1
        ):
            raise EntryStopImprovementError("maximum stop risk must be in (0, 1)")
        if self.parameter_count < 0 or self.parameter_count > 2:
            raise EntryStopImprovementError("stop parameter search is unbounded")


@dataclass(frozen=True, slots=True)
class EntryStopPolicy:
    """Frozen DSI-009 research definitions and sufficiency thresholds."""

    comparison_start: str = "2021-01-01"
    comparison_end: str = "2025-12-24"
    recovery_window_sessions: int = 20
    quick_recovery_sessions: int = 10
    recovery_return_threshold: float = 0.05
    tail_loss_threshold: float = -0.10
    maximum_entry_extension_atr: float = 1.0
    maximum_entry_gap_fraction: float = 0.02
    minimum_challenger_trades: int = 20
    minimum_elite_completed: int = 30
    elite_accuracy_target: float = 0.75
    maximum_entry_challengers: int = 10
    maximum_stop_challengers: int = 10

    def __post_init__(self) -> None:
        if self.recovery_window_sessions < 1 or self.quick_recovery_sessions < 1:
            raise EntryStopImprovementError("recovery windows must be positive")
        if self.minimum_challenger_trades < 1:
            raise EntryStopImprovementError(
                "minimum challenger trades must be positive"
            )
        if not 0 < self.elite_accuracy_target < 1:
            raise EntryStopImprovementError("Elite target must be in (0, 1)")


@dataclass(frozen=True, slots=True)
class EntryStopSourcePaths:
    """Caller-selected immutable DSI-009 inputs."""

    dsi008_certificate: Path
    dsi007_certificate: Path
    database: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class EntryStopImprovementResult:
    """Deterministic DSI-009 rows and conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )


__all__ = [
    "DSI009_CONTRACT_VERSION",
    "DSI009_RESEARCH_SCOPE",
    "EntryChallengerState",
    "EntryMechanism",
    "EntryStopAttribution",
    "EntryStopImprovementError",
    "EntryStopImprovementResult",
    "EntryStopPolicy",
    "EntryStopSourcePaths",
    "FillState",
    "StopChallengerState",
    "StopMechanism",
    "StopValueState",
]
