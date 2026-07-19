from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
PLATFORM_VERSION = "ALPHA_DATA_PLATFORM_v1.0"
MANIFEST_SCHEMA_VERSION = "adp-manifest-v1"
DEFAULT_OUTPUT = ".alpha/data_platform/ALPHA_DATA_PLATFORM_v1.0"


class PlatformLayer(StrEnum):
    RAW = "RAW"
    NORMALIZED = "NORMALIZED"
    HISTORICAL_TRUTH = "HISTORICAL_TRUTH"
    CANONICAL_WAREHOUSE = "CANONICAL_WAREHOUSE"
    REPLAY_CACHE = "REPLAY_CACHE"


class DatasetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED = "DEPRECATED"


class DatasetCategory(StrEnum):
    DAILY_OHLCV = "DAILY_OHLCV"
    DELIVERY = "DELIVERY"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    SECURITY_MASTER = "SECURITY_MASTER"
    IDENTITY = "IDENTITY"
    SYMBOL_HISTORY = "SYMBOL_HISTORY"
    TRADING_CALENDAR = "TRADING_CALENDAR"
    INDEX_OHLCV = "INDEX_OHLCV"
    INDEX_MEMBERSHIP = "INDEX_MEMBERSHIP"


class TruthClass(StrEnum):
    OFFICIAL = "OFFICIAL"
    OBSERVED = "OBSERVED"
    RECONCILED = "RECONCILED"
    DERIVED = "DERIVED"
    CURRENT_ONLY = "CURRENT_ONLY"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    CONFLICTING = "CONFLICTING"
    QUARANTINED = "QUARANTINED"


class FieldType(StrEnum):
    TEXT = "TEXT"
    DATE = "DATE"
    DATETIME = "DATETIME"
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"


class ReconciliationIssueType(StrEnum):
    PRICE_MISMATCH = "PRICE_MISMATCH"
    VOLUME_MISMATCH = "VOLUME_MISMATCH"
    MISSING_SESSION = "MISSING_SESSION"
    MISSING_OBSERVATION = "MISSING_OBSERVATION"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    CORPORATE_ACTION_MISMATCH = "CORPORATE_ACTION_MISMATCH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class DownloadStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CORRUPT = "CORRUPT"


class QuerySubject(StrEnum):
    OHLCV = "OHLCV"
    DELIVERY = "DELIVERY"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    SECURITY_MASTER = "SECURITY_MASTER"
    INDEX_MEMBERSHIP = "INDEX_MEMBERSHIP"
    INDEX_OHLCV = "INDEX_OHLCV"
    TRADING_CALENDAR = "TRADING_CALENDAR"


class WarehouseReleaseStatus(StrEnum):
    PLANNED = "PLANNED"
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


type Scalar = str | int | bool | Decimal | date | datetime | None


@dataclass(frozen=True, slots=True)
class LayerContract:
    layer: PlatformLayer
    mutable: bool
    business_logic_allowed: bool
    derived_indicators_allowed: bool
    regenerative: bool
    purpose: str


@dataclass(frozen=True, slots=True)
class RawArtifactMetadata:
    artifact_id: str
    dataset_id: str
    source: str
    original_filename: str
    source_timestamp: datetime | None
    retrieval_timestamp: datetime
    checksum: str
    compression: str | None
    content_type: str
    byte_size: int
    relative_path: str
    source_metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieval_timestamp", utc(self.retrieval_timestamp))
        if self.source_timestamp is not None:
            object.__setattr__(self, "source_timestamp", utc(self.source_timestamp))
        if len(self.checksum) != 64 or self.byte_size < 0:
            raise ValueError("ADP raw artifact metadata is invalid")
        if self.relative_path.startswith("/") or ".." in self.relative_path.split("/"):
            raise ValueError("ADP raw artifact path must be relative and contained")
        object.__setattr__(
            self,
            "source_metadata",
            MappingProxyType(dict(sorted(self.source_metadata.items()))),
        )


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    dataset_id: str
    dataset_name: str
    version: str
    source: str
    official: bool
    download_date: date | None
    checksum: str | None
    coverage_start: date | None
    coverage_end: date | None
    schema_version: str
    confidence: ConfidenceLevel
    status: DatasetStatus
    category: DatasetCategory
    exchange: str
    entities: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        for value in (
            self.dataset_id,
            self.dataset_name,
            self.version,
            self.source,
            self.schema_version,
            self.exchange,
        ):
            if not value.strip():
                raise ValueError("ADP dataset identity fields cannot be blank")
        if self.coverage_start and self.coverage_end:
            if self.coverage_end < self.coverage_start:
                raise ValueError("ADP dataset coverage interval is invalid")
        if self.checksum is not None and len(self.checksum) != 64:
            raise ValueError("ADP dataset checksum must be SHA-256")
        if (self.download_date is None) != (self.checksum is None):
            raise ValueError("download date and checksum must be recorded together")
        object.__setattr__(
            self,
            "entities",
            tuple(
                sorted(dict.fromkeys(item.strip().upper() for item in self.entities))
            ),
        )

    @property
    def acquired(self) -> bool:
        return self.download_date is not None and self.checksum is not None


@dataclass(frozen=True, slots=True)
class SchemaField:
    name: str
    field_type: FieldType
    nullable: bool
    truth_class: TruthClass
    description: str


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    schema_version: str
    name: str
    layer: PlatformLayer
    primary_key: tuple[str, ...]
    fields: tuple[SchemaField, ...]

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.fields)
        if not self.schema_version.strip() or not names:
            raise ValueError("ADP schema identity and fields are required")
        if len(set(names)) != len(names):
            raise ValueError("ADP schema field names must be unique")
        if not set(self.primary_key).issubset(names):
            raise ValueError("ADP schema primary key references unknown fields")


@dataclass(frozen=True, slots=True)
class SchemaValidationResult:
    schema_version: str
    valid: bool
    missing_fields: tuple[str, ...]
    unexpected_fields: tuple[str, ...]
    invalid_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransformationStep:
    step_id: str
    layer: PlatformLayer
    operation: str
    code_version: str
    input_checksum: str
    output_checksum: str


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    provenance_id: str
    observation_key: str
    dataset_id: str
    source: str
    transformation_chain: tuple[TransformationStep, ...]
    warehouse_version: str
    confidence: ConfidenceLevel
    validation_status: ValidationStatus
    field_truth: Mapping[str, TruthClass]
    last_verified: datetime | None
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field_truth",
            MappingProxyType(dict(sorted(self.field_truth.items()))),
        )
        if self.last_verified is not None:
            object.__setattr__(self, "last_verified", utc(self.last_verified))
        if len(self.checksum) != 64:
            raise ValueError("ADP provenance checksum must be SHA-256")


@dataclass(frozen=True, slots=True)
class ConfidenceEvidence:
    source_official: bool
    reconciled: bool
    completeness: Decimal
    corporate_actions_complete: bool
    identity_certainty: Decimal
    conflict_count: int
    unknown_field_count: int

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.completeness <= Decimal("1"):
            raise ValueError("ADP completeness must be between zero and one")
        if not Decimal("0") <= self.identity_certainty <= Decimal("1"):
            raise ValueError("ADP identity certainty must be between zero and one")
        if self.conflict_count < 0 or self.unknown_field_count < 0:
            raise ValueError("ADP confidence counts cannot be negative")


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    level: ConfidenceLevel
    score: Decimal
    reasons: tuple[str, ...]
    capped: bool


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    observation_id: str
    dataset_id: str
    observation_key: str
    source: str
    observed_on: date
    effective_from: date
    effective_to: date | None
    known_at: datetime
    fields: Mapping[str, Scalar]
    provenance_id: str
    warehouse_version: str

    def __post_init__(self) -> None:
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("ADP observation effective interval is invalid")
        object.__setattr__(self, "known_at", utc(self.known_at))
        object.__setattr__(
            self,
            "fields",
            MappingProxyType(dict(sorted(self.fields.items()))),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationSource:
    source: str
    observations: tuple[CanonicalObservation, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    issue_id: str
    issue_type: ReconciliationIssueType
    dataset_id: str
    observation_key: str
    sources: tuple[str, ...]
    details: str
    validation_status: ValidationStatus = ValidationStatus.CONFLICTING


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    compared_sources: tuple[str, ...]
    compared_observations: int
    matching_observations: int
    issues: tuple[ReconciliationIssue, ...]
    automatic_overwrites: int = 0

    def __post_init__(self) -> None:
        if self.automatic_overwrites != 0:
            raise ValueError("ADP reconciliation cannot overwrite observations")


@dataclass(frozen=True, slots=True)
class DownloadJob:
    job_id: str
    dataset_id: str
    partition: str
    requested_at: datetime
    expected_checksum: str | None
    incremental_after: date | None
    maximum_retries: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_at", utc(self.requested_at))
        if self.maximum_retries < 0:
            raise ValueError("ADP maximum retries cannot be negative")


@dataclass(frozen=True, slots=True)
class DownloadCheckpoint:
    job_id: str
    status: DownloadStatus
    next_offset: int
    attempts: int
    completed_parts: tuple[str, ...]
    checksum_verified: bool
    corruption_count: int
    last_error: str | None

    def __post_init__(self) -> None:
        if self.next_offset < 0 or self.attempts < 0 or self.corruption_count < 0:
            raise ValueError("ADP checkpoint counters cannot be negative")
        object.__setattr__(
            self,
            "completed_parts",
            tuple(sorted(dict.fromkeys(self.completed_parts))),
        )


@dataclass(frozen=True, slots=True)
class DataQuery:
    dataset_id: str
    subject: QuerySubject
    market_start: date | None = None
    market_end: date | None = None
    knowledge_as_of: datetime | None = None
    symbols: tuple[str, ...] = ()
    security_ids: tuple[str, ...] = ()
    index_ids: tuple[str, ...] = ()
    limit: int = 100

    def __post_init__(self) -> None:
        if self.market_start and self.market_end:
            if self.market_end < self.market_start:
                raise ValueError("ADP query interval is invalid")
        if self.knowledge_as_of is not None:
            object.__setattr__(self, "knowledge_as_of", utc(self.knowledge_as_of))
        if self.limit < 1:
            raise ValueError("ADP query limit must be positive")
        object.__setattr__(
            self,
            "symbols",
            tuple(sorted(dict.fromkeys(item.strip().upper() for item in self.symbols))),
        )
        object.__setattr__(
            self,
            "security_ids",
            tuple(sorted(dict.fromkeys(self.security_ids))),
        )
        object.__setattr__(
            self,
            "index_ids",
            tuple(
                sorted(dict.fromkeys(item.strip().upper() for item in self.index_ids))
            ),
        )


@dataclass(frozen=True, slots=True)
class QueryPlan:
    query_id: str
    dataset_id: str
    subject: QuerySubject
    filters: tuple[tuple[str, str], ...]
    point_in_time_enforced: bool
    warehouse_version: str
    dataset_version: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    plan: QueryPlan
    records: tuple[CanonicalObservation, ...]
    status: str


@dataclass(frozen=True, slots=True)
class TimeTravelSnapshot:
    market_date: date
    knowledge_as_of: datetime
    records: tuple[CanonicalObservation, ...]
    dataset_versions: Mapping[str, str]
    unknown_datasets: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_as_of", utc(self.knowledge_as_of))
        object.__setattr__(
            self,
            "dataset_versions",
            MappingProxyType(dict(sorted(self.dataset_versions.items()))),
        )


@dataclass(frozen=True, slots=True)
class WarehouseRelease:
    warehouse_version: str
    status: WarehouseReleaseStatus
    parent_version: str | None
    dataset_versions: Mapping[str, str]
    schema_versions: tuple[str, ...]
    release_hash: str
    read_only: bool
    notes: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset_versions",
            MappingProxyType(dict(sorted(self.dataset_versions.items()))),
        )
        if len(self.release_hash) != 64:
            raise ValueError("ADP warehouse release hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class ReplayDataBinding:
    warehouse_version: str
    feature_version: str
    policy_version: str
    decision_version: str
    dataset_versions: Mapping[str, str]
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        versions = MappingProxyType(dict(sorted(self.dataset_versions.items())))
        object.__setattr__(self, "dataset_versions", versions)
        object.__setattr__(
            self,
            "binding_hash",
            stable_hash(
                {
                    "warehouse_version": self.warehouse_version,
                    "feature_version": self.feature_version,
                    "policy_version": self.policy_version,
                    "decision_version": self.decision_version,
                    "dataset_versions": dict(versions),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ADPManifest:
    platform_version: str
    manifest_schema_version: str
    registry_hash: str
    schema_catalog_hash: str
    warehouse_lineage_hash: str
    layer_contract_hash: str
    dataset_count: int
    schema_count: int
    warehouse_release_count: int
    downloaded_files: int
    migrated_warehouse_v1: bool
    replay_changed: bool
    production_influence: bool = PRODUCTION_INFLUENCE
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("ADP v1 cannot influence production")
        if self.downloaded_files != 0 or self.migrated_warehouse_v1:
            raise ValueError("ADP v1 cannot download or migrate historical data")
        if self.replay_changed:
            raise ValueError("ADP v1 cannot change replay")
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )


def stable_hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [name for name in globals() if not name.startswith("_")]
