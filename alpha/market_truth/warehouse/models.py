from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

PRODUCTION_INFLUENCE = False
WAREHOUSE_SCHEMA_VERSION = "warehouse-v1"


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class WarehouseDataset(StrEnum):
    BHAVCOPY = "BHAVCOPY"
    SECURITIES = "SECURITIES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    INDICES = "INDICES"
    DELIVERABLES = "DELIVERABLES"
    CALENDAR = "CALENDAR"


class AcquisitionMethod(StrEnum):
    AUTOMATED = "AUTOMATED"
    MANUAL_IMPORT = "MANUAL_IMPORT"


class AuthorisationStatus(StrEnum):
    AUTHORISED = "AUTHORISED"
    MANUAL_IMPORT_ONLY = "MANUAL_IMPORT_ONLY"
    LICENCE_REQUIRED = "LICENCE_REQUIRED"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class IngestionStatus(StrEnum):
    ARCHIVED = "ARCHIVED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PARTIAL = "PARTIAL"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class SessionState(StrEnum):
    EXPECTED = "EXPECTED"
    AVAILABLE = "AVAILABLE"
    IMPORTED = "IMPORTED"
    VALIDATED = "VALIDATED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    HOLIDAY = "HOLIDAY"
    SPECIAL_SESSION = "SPECIAL_SESSION"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"


class WarehouseQualityState(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    QUARANTINED = "QUARANTINED"
    UNAVAILABLE = "UNAVAILABLE"


class ReconciliationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CONFLICTING = "CONFLICTING"
    INCOMPLETE = "INCOMPLETE"
    DUPLICATE = "DUPLICATE"
    REVISED = "REVISED"
    QUARANTINED = "QUARANTINED"


class AdjustmentStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    APPLIED = "APPLIED"
    INCOMPLETE = "INCOMPLETE"
    QUARANTINED = "QUARANTINED"


class AdjustmentMode(StrEnum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"
    POINT_IN_TIME = "POINT_IN_TIME"


class DividendMode(StrEnum):
    PRICE_ADJUSTED = "PRICE_ADJUSTED"
    TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"
    UNADJUSTED = "UNADJUSTED"


class CorporateActionKind(StrEnum):
    DIVIDEND = "DIVIDEND"
    SPECIAL_DIVIDEND = "SPECIAL_DIVIDEND"
    INTERIM_DIVIDEND = "INTERIM_DIVIDEND"
    FINAL_DIVIDEND = "FINAL_DIVIDEND"
    STOCK_SPLIT = "STOCK_SPLIT"
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
    LISTING = "LISTING"
    DELISTING = "DELISTING"
    SUSPENSION = "SUSPENSION"
    RELISTING = "RELISTING"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    OTHER = "OTHER"


class AggregatePeriod(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


@dataclass(frozen=True, slots=True)
class WarehousePaths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def database(self) -> Path:
        return self.root / "warehouse.duckdb"

    @property
    def manifest(self) -> Path:
        return self.root / "metadata" / "raw_manifest.json"

    @property
    def publications(self) -> Path:
        return self.root / "publications"


@dataclass(frozen=True, slots=True)
class SourceAuthorisation:
    record_id: str
    provider: str
    dataset: WarehouseDataset
    acquisition_method: AcquisitionMethod
    authorisation_basis: str
    internal_storage_permitted: bool
    internal_research_permitted: bool
    redistribution_permitted: bool
    retention_permitted: bool
    effective_date: date
    expiry_date: date | None
    evidence_reference: str
    status: AuthorisationStatus

    def __post_init__(self) -> None:
        if not self.record_id.strip() or not self.provider.strip():
            raise ValueError("authorisation record id and provider are required")
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("authorisation expiry cannot precede effective date")
        if self.redistribution_permitted:
            raise ValueError("warehouse authorisations cannot enable redistribution")


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    source_file_id: str
    provider: str
    dataset_type: WarehouseDataset
    exchange: Exchange
    trading_date: date | None
    publication_timestamp: datetime | None
    retrieval_timestamp: datetime
    original_filename: str
    content_type: str
    file_size: int
    sha256: str
    schema_fingerprint: str
    authorisation_record_id: str
    ingestion_status: IngestionStatus
    vault_path: str
    supersedes_file_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieval_timestamp", _utc(self.retrieval_timestamp))
        if self.publication_timestamp is not None:
            object.__setattr__(
                self, "publication_timestamp", _utc(self.publication_timestamp)
            )
        if self.file_size < 0 or len(self.sha256) != 64:
            raise ValueError("source file metadata is invalid")


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    exchange: Exchange
    security_id: str
    symbol: str
    series: str | None
    isin: str | None
    company_name: str | None
    instrument_type: str | None
    listing_date: date | None
    delisting_date: date | None
    suspension_intervals: tuple[tuple[date, date | None], ...]
    relisting_intervals: tuple[tuple[date, date | None], ...]
    symbol_valid_from: date
    symbol_valid_to: date | None
    series_valid_from: date
    series_valid_to: date | None
    identity_authority: str
    identity_confidence: Decimal
    source_file_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if self.isin is not None:
            object.__setattr__(self, "isin", self.isin.strip().upper())
        if not Decimal("0") <= self.identity_confidence <= Decimal("100"):
            raise ValueError("identity confidence must be between 0 and 100")
        if self.symbol_valid_to and self.symbol_valid_to < self.symbol_valid_from:
            raise ValueError("symbol validity interval is invalid")


@dataclass(frozen=True, slots=True)
class CanonicalDailyRecord:
    exchange: Exchange
    trading_date: date
    security_id: str
    symbol_as_traded: str
    series: str | None
    isin: str | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    last_price: Decimal | None
    previous_close: Decimal | None
    volume: Decimal
    turnover: Decimal | None
    trade_count: int | None
    vwap: Decimal | None
    deliverable_quantity: Decimal | None
    deliverable_percentage: Decimal | None
    upper_price_band: Decimal | None
    lower_price_band: Decimal | None
    source_file_id: str
    quality_state: WarehouseQualityState
    confidence: Decimal
    dataset_version: str
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_as_traded", self.symbol_as_traded.upper())
        if min(self.open, self.high, self.low, self.close, self.volume) < 0:
            raise ValueError("daily values cannot be negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("daily high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("daily low is above another OHLC value")
        if not Decimal("0") <= self.confidence <= Decimal("100"):
            raise ValueError("daily confidence must be between 0 and 100")
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "record_checksum"
        }
        object.__setattr__(self, "record_checksum", stable_hash(payload))


@dataclass(frozen=True, slots=True)
class IndexDailyRecord:
    exchange: Exchange
    index_id: str
    index_name: str
    trading_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    source_file_id: str
    dataset_version: str
    volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DeliverableRecord:
    exchange: Exchange
    trading_date: date
    security_id: str
    symbol: str
    series: str | None
    deliverable_quantity: Decimal | None
    deliverable_percentage: Decimal | None
    source_file_id: str


@dataclass(frozen=True, slots=True)
class CorporateActionRecord:
    corporate_action_id: str
    security_id: str
    exchange: Exchange
    action_type: CorporateActionKind
    announcement_date: date
    ex_date: date | None
    record_date: date | None
    effective_date: date | None
    payment_date: date | None
    ratio_numerator: Decimal | None
    ratio_denominator: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    old_symbol: str | None
    new_symbol: str | None
    old_isin: str | None
    new_isin: str | None
    source_file_id: str
    raw_terms: str
    normalised_terms: str
    evidence_class: str
    confidence: Decimal
    reconciliation_status: ReconciliationStatus
    adjustment_status: AdjustmentStatus
    version: str


@dataclass(frozen=True, slots=True)
class AdjustedDailyRecord:
    raw: CanonicalDailyRecord
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adjustment_policy_version: str
    corporate_action_version: str
    cumulative_price_factor: Decimal
    cumulative_volume_factor: Decimal
    adjustment_as_of: date
    source_event_ids: tuple[str, ...]
    mode: AdjustmentMode


@dataclass(frozen=True, slots=True)
class AggregateBar:
    period: AggregatePeriod
    exchange: Exchange
    security_id: str
    symbol: str
    period_start: date
    period_end: date
    first_trading_date: date
    last_trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    trade_count: int | None
    vwap: Decimal | None
    session_count: int
    expected_session_count: int
    completeness: Decimal
    source_daily_version: str
    adjustment_policy_version: str


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    trading_date: date
    exchange: Exchange
    security_id: str
    symbol: str
    series: str | None
    listed: bool
    suspended: bool
    tradable: bool
    eligible_for_research: bool
    eligibility_reason: str
    identity_version: str
    universe_version: str


@dataclass(frozen=True, slots=True)
class SessionInventoryRecord:
    exchange: Exchange
    session_date: date
    state: SessionState
    source_file_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_file: SourceFileRecord
    accepted_records: int
    rejected_records: int
    duplicate_records: int
    status: IngestionStatus
    reasons: tuple[str, ...]
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    version: str
    raw_manifest_hash: str
    session_range_start: date | None
    session_range_end: date | None
    exchange_coverage: tuple[Exchange, ...]
    security_count: int
    record_count: int
    identity_version: str
    corporate_action_version: str
    adjustment_policy_version: str
    quality_report_hash: str
    build_timestamp: datetime
    code_commit: str | None
    parent_version: str | None


@dataclass(frozen=True, slots=True)
class QualityComponent:
    name: str
    state: WarehouseQualityState
    checked_records: int
    affected_records: int
    explanation: str


@dataclass(frozen=True, slots=True)
class WarehouseQualityReport:
    generated_at: datetime
    components: tuple[QualityComponent, ...]
    quarantined_records: int
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    current_sessions: int
    warehouse_sessions: int
    overlapping_sessions: int
    missing_sessions: int
    extra_sessions: int
    current_symbols: int
    warehouse_symbols: int
    symbol_overlap: int
    compared_rows: int
    matching_rows: int
    ohlcv_differences: int
    identity_differences: int
    corporate_action_affected_differences: int
    unexplained_differences: int
    quarantine_candidates: int


@dataclass(frozen=True, slots=True)
class WarehouseStatus:
    source_files: int
    validated_source_files: int
    daily_records: int
    identity_records: int
    corporate_actions: int
    adjusted_records: int
    aggregate_records: int
    universe_records: int
    quarantined_records: int
    latest_version: str | None
    latest_published_version: str | None
    production_influence: bool = PRODUCTION_INFLUENCE


def stable_hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "PRODUCTION_INFLUENCE",
    "AcquisitionMethod",
    "AdjustedDailyRecord",
    "AdjustmentMode",
    "AdjustmentStatus",
    "AggregateBar",
    "AggregatePeriod",
    "AuthorisationStatus",
    "CanonicalDailyRecord",
    "CorporateActionKind",
    "CorporateActionRecord",
    "DatasetVersion",
    "DeliverableRecord",
    "DividendMode",
    "Exchange",
    "IdentityRecord",
    "IngestionResult",
    "IngestionStatus",
    "IndexDailyRecord",
    "QualityComponent",
    "ReconciliationReport",
    "ReconciliationStatus",
    "SessionInventoryRecord",
    "SessionState",
    "SourceAuthorisation",
    "SourceFileRecord",
    "UniverseMembership",
    "WAREHOUSE_SCHEMA_VERSION",
    "WarehouseDataset",
    "WarehousePaths",
    "WarehouseQualityReport",
    "WarehouseQualityState",
    "WarehouseStatus",
    "stable_hash",
]
