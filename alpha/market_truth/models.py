from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

PRODUCTION_INFLUENCE = False
MARKET_TRUTH_SCHEMA_VERSION = "market-truth-v1"


class DatasetKind(StrEnum):
    IDENTITY = "IDENTITY"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    TICK = "TICK"
    MINUTE_1 = "MINUTE_1"
    MINUTE_5 = "MINUTE_5"
    CALENDAR = "CALENDAR"
    INDEX = "INDEX"
    FUNDAMENTAL = "FUNDAMENTAL"
    UNIVERSE = "UNIVERSE"


class PriceHistoryMode(StrEnum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"
    POINT_IN_TIME = "POINT_IN_TIME"


class ProviderClass(StrEnum):
    NSE_OFFICIAL = "NSE_OFFICIAL"
    BSE_OFFICIAL = "BSE_OFFICIAL"
    LICENSED_HISTORICAL_ARCHIVE = "LICENSED_HISTORICAL_ARCHIVE"
    LICENSED_LIVE_FEED = "LICENSED_LIVE_FEED"
    BROKER_FALLBACK = "BROKER_FALLBACK"
    LOCAL_CACHE = "LOCAL_CACHE"


class ProviderHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNCONFIGURED = "UNCONFIGURED"
    UNKNOWN = "UNKNOWN"


class EvidenceClass(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    LICENSED = "LICENSED"
    BROKER_OBSERVED = "BROKER_OBSERVED"
    CACHED_AUTHORITATIVE = "CACHED_AUTHORITATIVE"
    FORWARD_OBSERVED = "FORWARD_OBSERVED"
    RECONSTRUCTED = "RECONSTRUCTED"
    UNKNOWN = "UNKNOWN"


class DataQuality(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ConfidenceBand(StrEnum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class SecurityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class IdentityAuthority(StrEnum):
    EXCHANGE = "EXCHANGE"
    LICENSED_MASTER = "LICENSED_MASTER"
    BROKER = "BROKER"
    LOCAL = "LOCAL"
    UNKNOWN = "UNKNOWN"


class CorporateActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    SPECIAL_DIVIDEND = "SPECIAL_DIVIDEND"
    INTERIM_DIVIDEND = "INTERIM_DIVIDEND"
    FINAL_DIVIDEND = "FINAL_DIVIDEND"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    AMALGAMATION = "AMALGAMATION"
    SCHEME_OF_ARRANGEMENT = "SCHEME_OF_ARRANGEMENT"
    FACE_VALUE_CHANGE = "FACE_VALUE_CHANGE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    NAME_CHANGE = "NAME_CHANGE"
    DELISTING = "DELISTING"
    LISTING = "LISTING"
    SUSPENSION = "SUSPENSION"
    RELISTING = "RELISTING"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    OTHER = "OTHER"


class TradingSessionType(StrEnum):
    FULL = "FULL"
    HALF = "HALF"
    HOLIDAY = "HOLIDAY"


@dataclass(frozen=True, slots=True)
class MarketTruthRequest:
    dataset: DatasetKind
    symbols: tuple[str, ...] = ()
    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None
    provider_hint: str | None = None
    maximum_age_seconds: int | None = None
    price_mode: PriceHistoryMode = PriceHistoryMode.RAW
    warehouse_version: str | None = None

    def __post_init__(self) -> None:
        if self.start is not None:
            object.__setattr__(self, "start", utc(self.start))
        if self.end is not None:
            object.__setattr__(self, "end", utc(self.end))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", utc(self.as_of))
        symbols = tuple(
            dict.fromkeys(item.strip().upper() for item in self.symbols if item.strip())
        )
        object.__setattr__(self, "symbols", symbols)
        if self.start and self.end and self.start > self.end:
            raise ValueError("market truth request start cannot follow end")
        if self.as_of and self.end and self.as_of < self.end:
            raise ValueError("point-in-time as_of cannot precede request end")
        if self.provider_hint is not None and not self.provider_hint.strip():
            raise ValueError("provider hint cannot be blank")
        if self.maximum_age_seconds is not None and self.maximum_age_seconds < 0:
            raise ValueError("maximum data age cannot be negative")
        if self.warehouse_version is not None and not self.warehouse_version.strip():
            raise ValueError("warehouse version cannot be blank")

    @property
    def request_id(self) -> str:
        digest = sha256(canonical_json(self.as_dict()).encode()).hexdigest()
        return "mte-request-" + digest[:24]

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset.value,
            "symbols": list(self.symbols),
            "start": _datetime_text(self.start),
            "end": _datetime_text(self.end),
            "as_of": _datetime_text(self.as_of),
            "provider_hint": self.provider_hint,
            "maximum_age_seconds": self.maximum_age_seconds,
            "price_mode": self.price_mode.value,
            "warehouse_version": self.warehouse_version,
        }


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    observed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    interval: DatasetKind
    exchange: str | None = None
    series: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "observed_at", utc(self.observed_at))
        if not self.symbol:
            raise ValueError("market bar symbol cannot be blank")
        if self.interval not in {
            DatasetKind.DAILY,
            DatasetKind.WEEKLY,
            DatasetKind.MONTHLY,
            DatasetKind.MINUTE_1,
            DatasetKind.MINUTE_5,
        }:
            raise ValueError("market bar interval is not bar-compatible")


@dataclass(frozen=True, slots=True)
class MarketTick:
    symbol: str
    observed_at: datetime
    last_price: Decimal
    quantity: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    exchange: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "observed_at", utc(self.observed_at))
        if not self.symbol:
            raise ValueError("market tick symbol cannot be blank")


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    symbol: str
    series: str | None
    isin: str | None
    security_id: str
    status: SecurityStatus
    effective_from: date
    effective_to: date | None
    continuity_id: str
    authority: IdentityAuthority

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if self.isin is not None:
            object.__setattr__(self, "isin", self.isin.strip().upper())
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("identity interval end cannot precede start")


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    security_id: str
    symbol: str
    action_type: CorporateActionType
    ex_date: date
    record_date: date | None = None
    ratio: str | None = None
    predecessor_symbol: str | None = None
    successor_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class TradingSession:
    session_date: date
    session_type: TradingSessionType
    settlement_date: date | None
    exchange: str


@dataclass(frozen=True, slots=True)
class IndexObservation:
    index_id: str
    observed_at: datetime
    value: Decimal
    currency: str = "INR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    security_id: str
    symbol: str
    metric: str
    value: Decimal
    period_end: date
    published_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "published_at", utc(self.published_at))


@dataclass(frozen=True, slots=True)
class UniverseObservation:
    security_id: str
    symbol: str
    exchange: str
    observed_on: date
    series: str | None
    listed: bool
    suspended: bool
    tradable: bool
    eligible_for_research: bool
    eligibility_reason: str
    identity_version: str
    universe_version: str


type MarketTruthRecord = (
    MarketBar
    | MarketTick
    | SecurityIdentity
    | CorporateAction
    | TradingSession
    | IndexObservation
    | FundamentalObservation
    | UniverseObservation
)


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    provider_class: ProviderClass
    display_name: str
    capabilities: tuple[DatasetKind, ...]
    priority: int
    authoritative: bool
    configured: bool
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider id cannot be blank")
        if self.priority < 0:
            raise ValueError("provider priority cannot be negative")
        if self.production_influence:
            raise ValueError("market truth providers cannot influence production")


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider_id: str
    state: ProviderHealthState
    checked_at: datetime
    latency_ms: int | None
    message: str
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", utc(self.checked_at))
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("provider latency cannot be negative")


@dataclass(frozen=True, slots=True)
class ProviderDataset:
    request_id: str
    provider_id: str
    source: str
    evidence_class: EvidenceClass
    observed_at: datetime
    records: tuple[MarketTruthRecord, ...]
    reported_completeness: Decimal
    source_reference: str
    warnings: tuple[str, ...] = ()
    checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", utc(self.observed_at))
        if not Decimal("0") <= self.reported_completeness <= Decimal("1"):
            raise ValueError("reported completeness must be between zero and one")
        payload = {
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "source": self.source,
            "evidence_class": self.evidence_class.value,
            "observed_at": self.observed_at.isoformat(),
            "records": [record_as_dict(item) for item in self.records],
            "reported_completeness": str(self.reported_completeness),
            "source_reference": self.source_reference,
            "warnings": list(self.warnings),
        }
        object.__setattr__(
            self, "checksum", sha256(canonical_json(payload).encode()).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider_id: str
    attempted_at: datetime
    succeeded: bool
    reason: str
    dataset_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempted_at", utc(self.attempted_at))


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    quality: DataQuality
    completeness: Decimal
    valid_records: int
    rejected_records: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    confidence_pct: Decimal
    band: ConfidenceBand
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    provenance_id: str
    request_id: str
    source: str
    provider_id: str
    source_reference: str
    provider_checksum: str | None
    lineage_hash: str
    attempts: tuple[ProviderAttempt, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", utc(self.generated_at))


@dataclass(frozen=True, slots=True)
class MarketTruth:
    request: MarketTruthRequest
    records: tuple[MarketTruthRecord, ...]
    source: str
    provider: str
    timestamp: datetime
    evidence_class: EvidenceClass
    confidence: ConfidenceAssessment
    quality: QualityAssessment
    version: str
    provenance: Provenance
    completeness: Decimal
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", utc(self.timestamp))
        if self.production_influence:
            raise ValueError("market truth objects cannot influence production")
        if self.completeness != self.quality.completeness:
            raise ValueError("truth completeness must match quality assessment")

    @property
    def available(self) -> bool:
        return self.quality.quality is not DataQuality.UNAVAILABLE

    @property
    def actionable(self) -> bool:
        return self.quality.quality is DataQuality.COMPLETE and bool(self.records)


@dataclass(frozen=True, slots=True)
class ProviderHealthReport:
    generated_at: datetime
    providers: tuple[ProviderHealth, ...]


@dataclass(frozen=True, slots=True)
class MarketTruthSystemReport:
    generated_at: datetime
    provider_count: int
    configured_providers: int
    healthy_providers: int
    degraded_providers: int
    unavailable_providers: int
    cached_datasets: int
    schema_version: str
    production_influence: bool = PRODUCTION_INFLUENCE


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def record_as_dict(record: MarketTruthRecord) -> dict[str, object]:
    if isinstance(record, MarketBar):
        return {
            "type": "MARKET_BAR",
            "symbol": record.symbol,
            "observed_at": record.observed_at.isoformat(),
            "open_price": str(record.open_price),
            "high_price": str(record.high_price),
            "low_price": str(record.low_price),
            "close_price": str(record.close_price),
            "volume": str(record.volume),
            "interval": record.interval.value,
            "exchange": record.exchange,
            "series": record.series,
        }
    if isinstance(record, MarketTick):
        return {
            "type": "MARKET_TICK",
            "symbol": record.symbol,
            "observed_at": record.observed_at.isoformat(),
            "last_price": str(record.last_price),
            "quantity": _decimal_text(record.quantity),
            "bid_price": _decimal_text(record.bid_price),
            "ask_price": _decimal_text(record.ask_price),
            "exchange": record.exchange,
        }
    if isinstance(record, SecurityIdentity):
        return {
            "type": "SECURITY_IDENTITY",
            "symbol": record.symbol,
            "series": record.series,
            "isin": record.isin,
            "security_id": record.security_id,
            "status": record.status.value,
            "effective_from": record.effective_from.isoformat(),
            "effective_to": _date_text(record.effective_to),
            "continuity_id": record.continuity_id,
            "authority": record.authority.value,
        }
    if isinstance(record, CorporateAction):
        return {
            "type": "CORPORATE_ACTION",
            "action_id": record.action_id,
            "security_id": record.security_id,
            "symbol": record.symbol,
            "action_type": record.action_type.value,
            "ex_date": record.ex_date.isoformat(),
            "record_date": _date_text(record.record_date),
            "ratio": record.ratio,
            "predecessor_symbol": record.predecessor_symbol,
            "successor_symbol": record.successor_symbol,
        }
    if isinstance(record, TradingSession):
        return {
            "type": "TRADING_SESSION",
            "session_date": record.session_date.isoformat(),
            "session_type": record.session_type.value,
            "settlement_date": _date_text(record.settlement_date),
            "exchange": record.exchange,
        }
    if isinstance(record, IndexObservation):
        return {
            "type": "INDEX_OBSERVATION",
            "index_id": record.index_id,
            "observed_at": record.observed_at.isoformat(),
            "value": str(record.value),
            "currency": record.currency,
        }
    if isinstance(record, UniverseObservation):
        return {
            "type": "UNIVERSE_OBSERVATION",
            "security_id": record.security_id,
            "symbol": record.symbol,
            "exchange": record.exchange,
            "observed_on": record.observed_on.isoformat(),
            "series": record.series,
            "listed": record.listed,
            "suspended": record.suspended,
            "tradable": record.tradable,
            "eligible_for_research": record.eligible_for_research,
            "eligibility_reason": record.eligibility_reason,
            "identity_version": record.identity_version,
            "universe_version": record.universe_version,
        }
    return {
        "type": "FUNDAMENTAL_OBSERVATION",
        "security_id": record.security_id,
        "symbol": record.symbol,
        "metric": record.metric,
        "value": str(record.value),
        "period_end": record.period_end.isoformat(),
        "published_at": record.published_at.isoformat(),
    }


def record_from_dict(payload: dict[str, object]) -> MarketTruthRecord:
    record_type = str(payload["type"])
    if record_type == "MARKET_BAR":
        return MarketBar(
            symbol=str(payload["symbol"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            open_price=Decimal(str(payload["open_price"])),
            high_price=Decimal(str(payload["high_price"])),
            low_price=Decimal(str(payload["low_price"])),
            close_price=Decimal(str(payload["close_price"])),
            volume=Decimal(str(payload["volume"])),
            interval=DatasetKind(str(payload["interval"])),
            exchange=_optional_text(payload.get("exchange")),
            series=_optional_text(payload.get("series")),
        )
    if record_type == "MARKET_TICK":
        return MarketTick(
            symbol=str(payload["symbol"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            last_price=Decimal(str(payload["last_price"])),
            quantity=_optional_decimal(payload.get("quantity")),
            bid_price=_optional_decimal(payload.get("bid_price")),
            ask_price=_optional_decimal(payload.get("ask_price")),
            exchange=_optional_text(payload.get("exchange")),
        )
    if record_type == "SECURITY_IDENTITY":
        return SecurityIdentity(
            symbol=str(payload["symbol"]),
            series=_optional_text(payload.get("series")),
            isin=_optional_text(payload.get("isin")),
            security_id=str(payload["security_id"]),
            status=SecurityStatus(str(payload["status"])),
            effective_from=date.fromisoformat(str(payload["effective_from"])),
            effective_to=_optional_date(payload.get("effective_to")),
            continuity_id=str(payload["continuity_id"]),
            authority=IdentityAuthority(str(payload["authority"])),
        )
    if record_type == "CORPORATE_ACTION":
        return CorporateAction(
            action_id=str(payload["action_id"]),
            security_id=str(payload["security_id"]),
            symbol=str(payload["symbol"]),
            action_type=CorporateActionType(str(payload["action_type"])),
            ex_date=date.fromisoformat(str(payload["ex_date"])),
            record_date=_optional_date(payload.get("record_date")),
            ratio=_optional_text(payload.get("ratio")),
            predecessor_symbol=_optional_text(payload.get("predecessor_symbol")),
            successor_symbol=_optional_text(payload.get("successor_symbol")),
        )
    if record_type == "TRADING_SESSION":
        return TradingSession(
            session_date=date.fromisoformat(str(payload["session_date"])),
            session_type=TradingSessionType(str(payload["session_type"])),
            settlement_date=_optional_date(payload.get("settlement_date")),
            exchange=str(payload["exchange"]),
        )
    if record_type == "INDEX_OBSERVATION":
        return IndexObservation(
            index_id=str(payload["index_id"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            value=Decimal(str(payload["value"])),
            currency=str(payload.get("currency", "INR")),
        )
    if record_type == "UNIVERSE_OBSERVATION":
        return UniverseObservation(
            security_id=str(payload["security_id"]),
            symbol=str(payload["symbol"]),
            exchange=str(payload["exchange"]),
            observed_on=date.fromisoformat(str(payload["observed_on"])),
            series=_optional_text(payload.get("series")),
            listed=bool(payload["listed"]),
            suspended=bool(payload["suspended"]),
            tradable=bool(payload["tradable"]),
            eligible_for_research=bool(payload["eligible_for_research"]),
            eligibility_reason=str(payload["eligibility_reason"]),
            identity_version=str(payload["identity_version"]),
            universe_version=str(payload["universe_version"]),
        )
    if record_type == "FUNDAMENTAL_OBSERVATION":
        return FundamentalObservation(
            security_id=str(payload["security_id"]),
            symbol=str(payload["symbol"]),
            metric=str(payload["metric"]),
            value=Decimal(str(payload["value"])),
            period_end=date.fromisoformat(str(payload["period_end"])),
            published_at=datetime.fromisoformat(str(payload["published_at"])),
        )
    raise ValueError(f"unsupported market truth record type: {record_type}")


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_text(value: datetime | None) -> str | None:
    return None if value is None else utc(value).isoformat()


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional_text(value: object) -> str | None:
    return None if value is None or str(value).strip() == "" else str(value)


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None or str(value).strip() == "" else Decimal(str(value))


def _optional_date(value: object) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    return date.fromisoformat(str(value))


__all__ = [
    "ConfidenceAssessment",
    "ConfidenceBand",
    "CorporateAction",
    "CorporateActionType",
    "DataQuality",
    "DatasetKind",
    "EvidenceClass",
    "FundamentalObservation",
    "IdentityAuthority",
    "IndexObservation",
    "MARKET_TRUTH_SCHEMA_VERSION",
    "MarketBar",
    "MarketTick",
    "MarketTruth",
    "MarketTruthRecord",
    "MarketTruthRequest",
    "MarketTruthSystemReport",
    "PRODUCTION_INFLUENCE",
    "ProviderAttempt",
    "ProviderClass",
    "ProviderDataset",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderHealthReport",
    "ProviderHealthState",
    "Provenance",
    "QualityAssessment",
    "SecurityIdentity",
    "SecurityStatus",
    "TradingSession",
    "TradingSessionType",
    "canonical_json",
    "record_as_dict",
    "record_from_dict",
    "utc",
]
