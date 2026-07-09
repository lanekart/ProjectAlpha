from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType


class LiveFeedStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    ERROR = "ERROR"


class FeedHealthStatus(StrEnum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class MarketSessionState(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    OPENING_AUCTION = "OPENING_AUCTION"
    OPEN = "OPEN"
    MID_SESSION = "MID_SESSION"
    POWER_HOUR = "POWER_HOUR"
    CLOSING_SESSION = "CLOSING_SESSION"
    POST_CLOSE = "POST_CLOSE"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class TickQualityStatus(StrEnum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"


class LiveRiskWarningType(StrEnum):
    LARGE_SPREAD = "LARGE_SPREAD"
    SPREAD_WIDENING = "SPREAD_WIDENING"
    PRICE_GAP = "PRICE_GAP"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    STALE_FEED = "STALE_FEED"
    MISSING_BARS = "MISSING_BARS"
    MISSING_TICKS = "MISSING_TICKS"
    ABNORMAL_VOLUME = "ABNORMAL_VOLUME"


@dataclass(frozen=True, slots=True)
class InstrumentSubscription:
    symbol: str
    instrument_key: str
    exchange: str = "NSE"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        instrument_key = self.instrument_key.strip()
        exchange = self.exchange.strip().upper()
        if not symbol:
            raise ValueError("subscription symbol cannot be empty")
        if not instrument_key:
            raise ValueError("subscription instrument key cannot be empty")
        if not exchange:
            raise ValueError("subscription exchange cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "instrument_key", instrument_key)
        object.__setattr__(self, "exchange", exchange)


@dataclass(frozen=True, slots=True)
class LiveTick:
    symbol: str
    price: Decimal
    volume: Decimal
    observed_at: datetime
    exchange_timestamp: datetime | None = None
    provider_timestamp: datetime | None = None
    received_at: datetime | None = None
    instrument_key: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("tick symbol cannot be empty")
        if self.price <= Decimal("0"):
            raise ValueError("tick price must be positive")
        if self.volume < Decimal("0"):
            raise ValueError("tick volume cannot be negative")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "price", Decimal(self.price))
        object.__setattr__(self, "volume", Decimal(self.volume))
        object.__setattr__(
            self,
            "instrument_key",
            self.instrument_key.strip() if self.instrument_key else None,
        )


@dataclass(frozen=True, slots=True)
class LiveQuote:
    symbol: str
    last_price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    volume: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("quote symbol cannot be empty")
        if self.last_price <= Decimal("0"):
            raise ValueError("quote last price must be positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "last_price", Decimal(self.last_price))
        object.__setattr__(self, "bid", None if self.bid is None else Decimal(self.bid))
        object.__setattr__(self, "ask", None if self.ask is None else Decimal(self.ask))
        object.__setattr__(self, "volume", Decimal(self.volume))


@dataclass(frozen=True, slots=True)
class LiveOHLCVBar:
    symbol: str
    started_at: datetime
    timeframe_minutes: int
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    vwap: Decimal | None

    def __post_init__(self) -> None:
        if self.timeframe_minutes <= 0:
            raise ValueError("timeframe must be positive")
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("bar symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class FeedHealthSnapshot:
    provider_name: str
    status: FeedHealthStatus
    provider_connected: bool
    authenticated: bool
    subscribed: bool
    heartbeat_received: bool
    heartbeat_age_seconds: Decimal | None
    last_tick_timestamp: datetime | None
    last_bar_timestamp: datetime | None
    reconnect_attempts: int
    stale_duration_seconds: Decimal | None
    provider_latency_seconds: Decimal | None
    feed_quality_score: Decimal
    observed_at: datetime
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider_name = self.provider_name.strip()
        reasons = tuple(reason.strip() for reason in self.reasons if reason.strip())
        if not provider_name:
            raise ValueError("provider name cannot be empty")
        if self.reconnect_attempts < 0:
            raise ValueError("reconnect attempts cannot be negative")
        if self.feed_quality_score < Decimal("0") or self.feed_quality_score > Decimal(
            "100"
        ):
            raise ValueError("feed quality score must be between 0 and 100")
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "status", FeedHealthStatus(self.status))
        object.__setattr__(self, "feed_quality_score", Decimal(self.feed_quality_score))
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class TickQualityAssessment:
    symbol: str
    status: TickQualityStatus
    reasons: tuple[str, ...]
    observed_at: datetime | None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons if reason.strip())
        if not symbol:
            raise ValueError("tick quality symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "status", TickQualityStatus(self.status))
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class TickQualityStatistics:
    total_ticks: int = 0
    valid_ticks: int = 0
    suspect_ticks: int = 0
    invalid_ticks: int = 0
    rejection_reasons: MappingProxyType[str, int] | dict[str, int] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        for field_name in (
            "total_ticks",
            "valid_ticks",
            "suspect_ticks",
            "invalid_ticks",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        reasons = {
            key.strip(): int(value)
            for key, value in self.rejection_reasons.items()
            if key.strip()
        }
        object.__setattr__(
            self,
            "rejection_reasons",
            MappingProxyType(dict(sorted(reasons.items()))),
        )


@dataclass(frozen=True, slots=True)
class LatencySample:
    symbol: str
    exchange_timestamp: datetime
    provider_timestamp: datetime
    alpha_receive_timestamp: datetime
    indicator_completion_timestamp: datetime
    recommendation_completion_timestamp: datetime

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("latency symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)

    @property
    def feed_latency(self) -> timedelta:
        return self.alpha_receive_timestamp - self.exchange_timestamp

    @property
    def provider_latency(self) -> timedelta:
        return self.provider_timestamp - self.exchange_timestamp

    @property
    def processing_latency(self) -> timedelta:
        return self.recommendation_completion_timestamp - self.alpha_receive_timestamp

    @property
    def end_to_end_latency(self) -> timedelta:
        return self.recommendation_completion_timestamp - self.exchange_timestamp


@dataclass(frozen=True, slots=True)
class LatencySummary:
    sample_count: int
    rolling_average_seconds: Decimal | None
    rolling_max_seconds: Decimal | None
    rolling_p95_seconds: Decimal | None
    rolling_p99_seconds: Decimal | None


@dataclass(frozen=True, slots=True)
class LiveRiskWarning:
    symbol: str
    warning_type: LiveRiskWarningType
    severity: str
    message: str
    why: str
    observed_at: datetime
    operator_action: str

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        severity = self.severity.strip().upper()
        message = self.message.strip()
        why = self.why.strip()
        operator_action = self.operator_action.strip()
        if not symbol:
            raise ValueError("risk warning symbol cannot be empty")
        if not severity:
            raise ValueError("risk warning severity cannot be empty")
        if not message or not why or not operator_action:
            raise ValueError("risk warning text cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "warning_type", LiveRiskWarningType(self.warning_type))
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "why", why)
        object.__setattr__(self, "operator_action", operator_action)
