"""Immutable domain models for the point-in-time historical universe."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Any

PRODUCTION_INFLUENCE = False
DATASET_VERSION = "point-in-time-historical-universe-v1.0"
SCHEMA_VERSION = "point-in-time-universe-schema-v1"
SUPPORTED_INDICES = ("NIFTY50", "NIFTY100", "NIFTY200", "NIFTY500")


class ConfidenceGrade(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class EvidenceStatus(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    CONFLICTED = "CONFLICTED"


class TradabilityStatus(StrEnum):
    TRADABLE = "TRADABLE"
    NOT_YET_LISTED = "NOT_YET_LISTED"
    DELISTED = "DELISTED"
    SUSPENDED = "SUSPENDED"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"


class SurvivorshipStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_UNKNOWN_HISTORY = "PASS_WITH_UNKNOWN_HISTORY"
    FAIL = "FAIL"


class SurvivorshipFailureCode(StrEnum):
    FUTURE_CONSTITUENT_LEAK = "FUTURE_CONSTITUENT_LEAK"
    SECURITY_BEFORE_LISTING = "SECURITY_BEFORE_LISTING"
    SECURITY_AFTER_DELISTING = "SECURITY_AFTER_DELISTING"
    SYMBOL_OUTSIDE_EFFECTIVE_INTERVAL = "SYMBOL_OUTSIDE_EFFECTIVE_INTERVAL"
    STALE_SECTOR_MAPPING = "STALE_SECTOR_MAPPING"
    UNKNOWN_INDEX_HISTORY = "UNKNOWN_INDEX_HISTORY"
    UNKNOWN_SECTOR_HISTORY = "UNKNOWN_SECTOR_HISTORY"
    UNKNOWN_CORPORATE_ACTION_HISTORY = "UNKNOWN_CORPORATE_ACTION_HISTORY"


@dataclass(frozen=True, slots=True)
class EffectiveInterval:
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective interval end cannot precede its start")

    def covers(self, value: date) -> bool:
        return value >= self.effective_from and (
            self.effective_to is None or value <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class HistoricalSymbol:
    symbol: str
    interval: EffectiveInterval
    source: str
    confidence: ConfidenceGrade

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized:
            raise ValueError("historical symbol cannot be empty")
        object.__setattr__(self, "symbol", normalized)


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    security_id: str
    current_symbol: str
    historical_symbols: tuple[HistoricalSymbol, ...]
    isin: str | None
    listing_date: date | None
    delisting_date: date | None
    exchange: str
    instrument_type: str
    active_status: str
    corporate_action_lineage: tuple[str, ...]
    source: str
    confidence: ConfidenceGrade

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security id cannot be empty")
        object.__setattr__(self, "current_symbol", self.current_symbol.strip().upper())
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        object.__setattr__(
            self, "instrument_type", self.instrument_type.strip().upper()
        )
        if self.isin is not None:
            object.__setattr__(self, "isin", self.isin.strip().upper())
        if self.delisting_date is not None and self.listing_date is not None:
            if self.delisting_date < self.listing_date:
                raise ValueError("delisting date cannot precede listing date")
        if not self.historical_symbols:
            raise ValueError("security requires at least one historical symbol")

    def symbol_on(self, value: date) -> str | None:
        matches = tuple(
            row.symbol for row in self.historical_symbols if row.interval.covers(value)
        )
        if len(matches) > 1:
            raise ValueError(f"overlapping symbol intervals for {self.security_id}")
        return matches[0] if matches else None

    def existed_on(self, value: date) -> bool | None:
        if self.listing_date is None:
            return None
        if value < self.listing_date:
            return False
        return self.delisting_date is None or value <= self.delisting_date


@dataclass(frozen=True, slots=True)
class SuspensionInterval:
    interval: EffectiveInterval
    source: str
    confidence: ConfidenceGrade


@dataclass(frozen=True, slots=True)
class ListingHistoryRecord:
    security_id: str
    listing_date: date | None
    first_tradable_date: date | None
    delisting_date: date | None
    suspensions: tuple[SuspensionInterval, ...]
    relisting_dates: tuple[date, ...]
    source: str
    confidence: ConfidenceGrade


@dataclass(frozen=True, slots=True)
class IndexEvidenceWindow:
    index_name: str
    interval: EffectiveInterval
    source: str
    confidence: ConfidenceGrade

    def __post_init__(self) -> None:
        normalized = normalize_index(self.index_name)
        object.__setattr__(self, "index_name", normalized)


@dataclass(frozen=True, slots=True)
class IndexMembershipRecord:
    security_id: str
    index_name: str
    interval: EffectiveInterval
    source: str
    confidence: ConfidenceGrade

    def __post_init__(self) -> None:
        object.__setattr__(self, "index_name", normalize_index(self.index_name))


@dataclass(frozen=True, slots=True)
class IndexMembershipSnapshot:
    as_of: date
    index_name: str
    members: tuple[str, ...]
    additions: tuple[str, ...]
    removals: tuple[str, ...]
    source: str | None
    confidence: ConfidenceGrade
    status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class SectorMembershipRecord:
    security_id: str
    sector: str
    industry: str | None
    interval: EffectiveInterval
    source: str
    confidence: ConfidenceGrade

    def __post_init__(self) -> None:
        if not self.sector.strip():
            raise ValueError("sector cannot be empty")


@dataclass(frozen=True, slots=True)
class CorporateActionRecord:
    action_id: str
    security_id: str
    action_type: CorporateActionType
    effective_date: date
    source: str
    confidence: ConfidenceGrade
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None
    old_symbol: str | None = None
    new_symbol: str | None = None
    predecessor_security_ids: tuple[str, ...] = ()
    successor_security_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("corporate action id cannot be empty")
        if self.action_type in {CorporateActionType.SPLIT, CorporateActionType.BONUS}:
            if self.ratio_numerator is None or self.ratio_denominator is None:
                raise ValueError("split and bonus actions require a ratio")
            if min(self.ratio_numerator, self.ratio_denominator) <= 0:
                raise ValueError("corporate action ratio must be positive")
        if self.action_type is CorporateActionType.SYMBOL_CHANGE:
            if not self.old_symbol or not self.new_symbol:
                raise ValueError("symbol changes require old and new symbols")


@dataclass(frozen=True, slots=True)
class UniverseObservation:
    as_of: date
    security_id: str
    symbol: str
    exchange: str
    source: str
    price_available: bool = True
    volume_available: bool = True


@dataclass(frozen=True, slots=True)
class UniverseMember:
    as_of: date
    security_id: str
    symbol: str
    exchange: str
    tradability: TradabilityStatus
    index_memberships: tuple[tuple[str, bool | None], ...]
    sector: str | None
    sector_status: EvidenceStatus
    listing_valid: bool | None
    corporate_action_status: EvidenceStatus
    confidence: ConfidenceGrade
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    as_of: date
    members: tuple[UniverseMember, ...]
    index_snapshots: tuple[IndexMembershipSnapshot, ...]
    confidence: ConfidenceGrade
    unknown_dimensions: tuple[str, ...]
    dataset_version: str = DATASET_VERSION


@dataclass(frozen=True, slots=True)
class SurvivorshipAuditRecord:
    as_of: date
    observed_universe_size: int
    invalid_security_count: int
    future_constituent_leaks: int
    stale_sector_mappings: int
    unknown_index_count: int
    unknown_sector_count: int
    failures: tuple[SurvivorshipFailureCode, ...]
    status: SurvivorshipStatus


@dataclass(frozen=True, slots=True)
class UniverseCoverage:
    first_session: date
    last_session: date
    sessions: int
    security_master_size: int
    instrument_types_known: int
    observation_rows: int
    sessions_with_universe: int
    index_known_sessions: tuple[tuple[str, int], ...]
    sector_known_security_intervals: int
    listing_dates_known: int
    delisting_dates_known: int
    corporate_actions_known: int
    unknown_history_percentage: Decimal
    survivorship_failures: int
    confidence: ConfidenceGrade


@dataclass(frozen=True, slots=True)
class UniverseManifest:
    build_id: str
    dataset_version: str
    schema_version: str
    generated_at: datetime
    source_database: str
    source_fingerprint: str
    coverage: UniverseCoverage
    production_influence: bool = PRODUCTION_INFLUENCE


def normalize_index(value: str) -> str:
    normalized = value.replace(" ", "").replace("_", "").upper()
    if normalized not in SUPPORTED_INDICES:
        raise ValueError(f"unsupported index: {value}")
    return normalized


def stable_hash(value: object) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


def deterministic_generated_at(last_session: date) -> datetime:
    return datetime.combine(last_session, datetime.min.time(), tzinfo=UTC)


__all__ = [
    "CorporateActionRecord",
    "CorporateActionType",
    "ConfidenceGrade",
    "DATASET_VERSION",
    "EffectiveInterval",
    "EvidenceStatus",
    "HistoricalSymbol",
    "IndexEvidenceWindow",
    "IndexMembershipRecord",
    "IndexMembershipSnapshot",
    "ListingHistoryRecord",
    "PRODUCTION_INFLUENCE",
    "SCHEMA_VERSION",
    "SUPPORTED_INDICES",
    "SectorMembershipRecord",
    "SecurityIdentity",
    "SuspensionInterval",
    "SurvivorshipAuditRecord",
    "SurvivorshipFailureCode",
    "SurvivorshipStatus",
    "TradabilityStatus",
    "UniverseCoverage",
    "UniverseManifest",
    "UniverseMember",
    "UniverseObservation",
    "UniverseSnapshot",
    "deterministic_generated_at",
    "normalize_index",
    "stable_hash",
]
