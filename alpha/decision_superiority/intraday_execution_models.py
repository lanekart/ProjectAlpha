"""Typed research-only contracts for DSI-013 intraday execution research."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI013_CONTRACT_VERSION = "DSI-013-v1.0.0"
DSI013_RESEARCH_SCOPE = "GOVERNED_DAILY_SELECTION_INTRADAY_EXECUTION_RESEARCH"
DSI013_SOURCE_ID = "UPSTOX_V3_HISTORICAL_CANDLE"
DSI013_PRIMARY_INTERVAL_MINUTES = 5


class IntradayExecutionError(ValueError):
    """Raised when the governed DSI-013 contract cannot be satisfied."""


class IntradayReadiness(StrEnum):
    """Fail-closed DSI-013 source and research decisions."""

    SOURCE_READY = "READY_FOR_GOVERNED_INTRADAY_SOURCE_RESEARCH"
    SOURCE_UNAVAILABLE = "BLOCKED_BY_INTRADAY_SOURCE_UNAVAILABLE"
    IDENTITY_DEFECT = "BLOCKED_BY_INTRADAY_IDENTITY_DEFECT"
    SESSION_INTEGRITY_DEFECT = "BLOCKED_BY_INTRADAY_SESSION_INTEGRITY_DEFECT"
    DAILY_RECONCILIATION_DEFECT = "BLOCKED_BY_DAILY_INTRADAY_RECONCILIATION_DEFECT"
    NO_IMPROVEMENT = "READY_WITH_NO_INTRADAY_ENTRY_IMPROVEMENT"
    BELOW_ACCEPTANCE = "READY_WITH_DESCRIPTIVE_INTRADAY_IMPROVEMENT_BELOW_ACCEPTANCE"
    DESCRIPTIVE_IMPROVEMENT = (
        "READY_WITH_INTRADAY_EXECUTION_IMPROVEMENT_DESCRIPTIVE_ONLY"
    )
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_INTRADAY_SAMPLE"
    COST_STRESS_FAILED = "FAILED_COST_OR_SLIPPAGE_STRESS"
    CAPACITY_FAILED = "FAILED_CAPACITY_OR_CONCENTRATION"
    MULTIPLE_TESTING_FAILED = "FAILED_MULTIPLE_TESTING_CONTROL"
    INDEPENDENT_VALIDATION_INSUFFICIENT = "INSUFFICIENT_INDEPENDENT_VALIDATION"


class IntradayMechanismId(StrEnum):
    """The one control and four pre-registered DSI-013 challengers."""

    NEXT_SESSION_OPEN = "ENTRY-NEXT-SESSION-OPEN"
    ORB15_BREAKOUT = "ENTRY-ORB15-BREAKOUT"
    VWAP_RECLAIM = "ENTRY-VWAP-RECLAIM"
    FIRST_PULLBACK = "ENTRY-FIRST-PULLBACK"
    CLOSING_CONTINUATION = "ENTRY-CLOSING-CONTINUATION"


class IntradayBarDisposition(StrEnum):
    """Validation disposition for a broker-sourced intraday bar."""

    ADMITTED = "ADMITTED"
    DUPLICATE_TIMESTAMP = "DUPLICATE_TIMESTAMP"
    TIMESTAMP_MISALIGNED = "TIMESTAMP_MISALIGNED"
    OFF_SESSION = "OFF_SESSION"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    IMPOSSIBLE_OHLC = "IMPOSSIBLE_OHLC"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    NEGATIVE_OPEN_INTEREST = "NEGATIVE_OPEN_INTEREST"


@dataclass(frozen=True, slots=True)
class IntradayExecutionPolicy:
    """Pre-registered DSI-013 source, execution, cost, and acceptance policy."""

    interval_minutes: int = DSI013_PRIMARY_INTERVAL_MINUTES
    comparison_start: date = date(2022, 1, 1)
    comparison_end: date = date(2025, 12, 24)
    timezone_name: str = "Asia/Kolkata"
    session_start: time = time(9, 15)
    session_end: time = time(15, 30)
    last_standard_entry: time = time(14, 30)
    final_closing_fill: time = time(15, 15)
    request_timeout_seconds: float = 30.0
    maximum_bar_participation: float = 0.01
    maximum_daily_adv_participation: float = 0.01
    base_slippage_bps: float = 5.0
    stress_slippage_bps: float = 15.0
    minimum_cagr_improvement: float = 0.03
    maximum_drawdown_floor: float = -0.15
    maximum_drawdown_deterioration: float = 0.02
    minimum_calmar: float = 1.2
    minimum_profit_factor: float = 1.3

    def __post_init__(self) -> None:
        if self.interval_minutes != DSI013_PRIMARY_INTERVAL_MINUTES:
            raise IntradayExecutionError("DSI013_PRIMARY_INTERVAL_NOT_FROZEN")
        if self.comparison_start != date(2022, 1, 1):
            raise IntradayExecutionError("DSI013_COMPARISON_START_NOT_FROZEN")
        if self.comparison_end != date(2025, 12, 24):
            raise IntradayExecutionError("DSI013_COMPARISON_END_NOT_FROZEN")
        if self.comparison_start >= self.comparison_end:
            raise IntradayExecutionError("DSI013_COMPARISON_WINDOW_INVALID")
        if self.timezone_name != "Asia/Kolkata":
            raise IntradayExecutionError("DSI013_TIMEZONE_NOT_FROZEN")
        if self.session_start != time(9, 15) or self.session_end != time(15, 30):
            raise IntradayExecutionError("DSI013_SESSION_BOUNDARY_NOT_FROZEN")
        if not self.session_start < self.last_standard_entry < self.session_end:
            raise IntradayExecutionError("DSI013_LAST_ENTRY_TIME_INVALID")
        if not self.last_standard_entry < self.final_closing_fill < self.session_end:
            raise IntradayExecutionError("DSI013_FINAL_FILL_TIME_INVALID")
        if self.request_timeout_seconds <= 0:
            raise IntradayExecutionError("DSI013_REQUEST_TIMEOUT_INVALID")
        if not 0 < self.maximum_bar_participation <= 0.05:
            raise IntradayExecutionError("DSI013_BAR_PARTICIPATION_INVALID")
        if not 0 < self.maximum_daily_adv_participation <= 0.05:
            raise IntradayExecutionError("DSI013_DAILY_PARTICIPATION_INVALID")
        if not 0 <= self.base_slippage_bps < self.stress_slippage_bps:
            raise IntradayExecutionError("DSI013_SLIPPAGE_STRESS_INVALID")
        if self.minimum_cagr_improvement <= 0:
            raise IntradayExecutionError("DSI013_CAGR_IMPROVEMENT_INVALID")
        if not -1 < self.maximum_drawdown_floor < 0:
            raise IntradayExecutionError("DSI013_DRAWDOWN_FLOOR_INVALID")
        if not 0 <= self.maximum_drawdown_deterioration < 1:
            raise IntradayExecutionError("DSI013_DRAWDOWN_DETERIORATION_INVALID")
        if self.minimum_calmar <= 0 or self.minimum_profit_factor <= 0:
            raise IntradayExecutionError("DSI013_RISK_RETURN_TARGET_INVALID")

    @property
    def expected_regular_bar_count(self) -> int:
        """Return the expected number of five-minute bars in a regular NSE session."""

        start_minutes = self.session_start.hour * 60 + self.session_start.minute
        end_minutes = self.session_end.hour * 60 + self.session_end.minute
        return (end_minutes - start_minutes) // self.interval_minutes


@dataclass(frozen=True, slots=True)
class IntradaySourceRequest:
    """One candidate-bounded Upstox V3 historical-candle request."""

    governed_identity: str
    instrument_key: str
    from_date: date
    to_date: date

    def __post_init__(self) -> None:
        if not self.governed_identity.strip():
            raise IntradayExecutionError("DSI013_GOVERNED_IDENTITY_MISSING")
        if "|" not in self.instrument_key or not self.instrument_key.strip():
            raise IntradayExecutionError("DSI013_INSTRUMENT_KEY_INVALID")
        if self.from_date > self.to_date:
            raise IntradayExecutionError("DSI013_SOURCE_REQUEST_WINDOW_INVALID")
        if self.from_date < date(2022, 1, 1) or self.to_date > date(2025, 12, 24):
            raise IntradayExecutionError("DSI013_SOURCE_REQUEST_OUTSIDE_FROZEN_WINDOW")


@dataclass(frozen=True, slots=True)
class IntradayBar:
    """One parsed broker-sourced intraday candle with governed identity lineage."""

    governed_identity: str
    instrument_key: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int = 0


@dataclass(frozen=True, slots=True)
class IntradaySourcePaths:
    """Caller-selected immutable source chain for DSI-013."""

    dsi009_certificate: Path
    dsi008_certificate: Path
    dsi007_certificate: Path
    database: Path
    cache_root: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class IntradaySourceAudit:
    """Deterministic bar-level and session-level source validation evidence."""

    readiness: IntradayReadiness
    blockers: tuple[str, ...]
    bars: tuple[IntradayBar, ...]
    validation_rows: tuple[dict[str, Any], ...]
    session_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class IntradayExecutionResult:
    """Deterministic DSI-013 evidence, metrics, and decision."""

    source_commit: str
    readiness: IntradayReadiness
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )


__all__ = [
    "DSI013_CONTRACT_VERSION",
    "DSI013_PRIMARY_INTERVAL_MINUTES",
    "DSI013_RESEARCH_SCOPE",
    "DSI013_SOURCE_ID",
    "IntradayBar",
    "IntradayBarDisposition",
    "IntradayExecutionError",
    "IntradayExecutionPolicy",
    "IntradayExecutionResult",
    "IntradayMechanismId",
    "IntradayReadiness",
    "IntradaySourceAudit",
    "IntradaySourcePaths",
    "IntradaySourceRequest",
]
