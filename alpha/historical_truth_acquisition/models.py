from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
HTA_VERSION = "HTA_v1.0"
SECURITY_MASTER_VERSION = "SECURITY_MASTER_v1"
TRADING_CALENDAR_VERSION = "TRADING_CALENDAR_v1"
DAILY_MARKET_HISTORY_VERSION = "DAILY_MARKET_HISTORY_v1"
INDEX_HISTORY_VERSION = "INDEX_HISTORY_v1"
INDEX_MEMBERSHIP_VERSION = "INDEX_MEMBERSHIP_v1"
CORPORATE_ACTIONS_VERSION = "CORPORATE_ACTIONS_v1"
DELIVERY_HISTORY_VERSION = "DELIVERY_HISTORY_v1"
WAREHOUSE_CANDIDATE_VERSION = "WAREHOUSE_v2_CANDIDATE"
DEFAULT_HTA_OUTPUT = Path(".alpha/data_platform/HTA_v1.0")


class HTAStage(StrEnum):
    SECURITY_IDENTITY = "SECURITY_IDENTITY"
    TRADING_CALENDAR = "TRADING_CALENDAR"
    DAILY_EQUITY_HISTORY = "DAILY_EQUITY_HISTORY"
    INDEX_HISTORY = "INDEX_HISTORY"
    INDEX_MEMBERSHIP = "INDEX_MEMBERSHIP"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    DELIVERY_HISTORY = "DELIVERY_HISTORY"


class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    BLOCKED_SOURCE_UNAVAILABLE = "BLOCKED_SOURCE_UNAVAILABLE"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    FAILED = "FAILED"


class CheckpointStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CORRUPT = "CORRUPT"


class CertificationStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class WarehouseCandidateStatus(StrEnum):
    READY_FOR_ACTIVATION_REVIEW = "READY_FOR_ACTIVATION_REVIEW"
    NOT_READY = "NOT_READY"


class DiscrepancyType(StrEnum):
    PRICE_MISMATCH = "PRICE_MISMATCH"
    VOLUME_MISMATCH = "VOLUME_MISMATCH"
    MISSING_DAY = "MISSING_DAY"
    MISSING_OBSERVATION = "MISSING_OBSERVATION"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    CORPORATE_ACTION_MISMATCH = "CORPORATE_ACTION_MISMATCH"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class ConfidenceGrade(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StageDefinition:
    stage: HTAStage
    order: int
    version: str
    dataset_ids: tuple[str, ...]
    dependencies: tuple[HTAStage, ...]
    time_series: bool


@dataclass(frozen=True, slots=True)
class AcquisitionCheckpoint:
    checkpoint_id: str
    dataset_id: str
    source_key: str
    status: CheckpointStatus
    attempts: int
    completed_bytes: int
    checksum: str | None
    last_error: str | None
    next_retry_seconds: int
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "updated_at", _utc(self.updated_at))
        if self.attempts < 0 or self.completed_bytes < 0:
            raise ValueError("HTA checkpoint counters cannot be negative")
        if self.checksum is not None and len(self.checksum) != 64:
            raise ValueError("HTA checkpoint checksum must be SHA-256")


@dataclass(frozen=True, slots=True)
class DatasetEvidence:
    dataset_id: str
    source_files: int
    verified_files: int
    accepted_records: int
    rejected_records: int
    duplicate_records: int
    coverage_start: date | None
    coverage_end: date | None
    observed_sessions: int
    expected_sessions: int | None
    source_checksums: tuple[str, ...]
    source_file_ids: tuple[str, ...]
    schema_fingerprints: tuple[str, ...]
    unresolved_identity_records: int = 0

    @property
    def total_parsed_records(self) -> int:
        return self.accepted_records + self.rejected_records

    @property
    def parse_acceptance(self) -> Decimal | None:
        total = self.total_parsed_records
        if total == 0:
            return None
        return Decimal(self.accepted_records) / Decimal(total)

    @property
    def checksum_rate(self) -> Decimal | None:
        if self.source_files == 0:
            return None
        return Decimal(self.verified_files) / Decimal(self.source_files)

    @property
    def completeness(self) -> Decimal | None:
        if not self.expected_sessions:
            return None
        return min(
            Decimal("1"),
            Decimal(self.observed_sessions) / Decimal(self.expected_sessions),
        )


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    source_file_id: str
    dataset_id: str
    checksum: str
    schema_fingerprint: str
    accepted_records: int
    rejected_records: int
    duplicate_records: int
    coverage_start: date | None
    coverage_end: date | None
    observed_dates: tuple[date, ...]
    checksum_verified: bool
    unresolved_identity_records: int = 0


@dataclass(frozen=True, slots=True)
class IndexMembershipRecord:
    index_name: str
    effective_date: date
    alpha_security_id: str
    symbol: str
    isin: str | None
    change: str
    is_member: bool
    complete_snapshot: bool
    source_file_id: str
    source: str
    confidence: ConfidenceGrade


@dataclass(frozen=True, slots=True)
class AlphaSecurityIdentity:
    alpha_security_id: str
    isin: str | None
    exchanges: tuple[str, ...]
    current_symbols: tuple[str, ...]
    historical_symbols: tuple[str, ...]
    listing_date: date | None
    delisting_date: date | None
    source_file_ids: tuple[str, ...]
    confidence: ConfidenceGrade


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    finding_id: str
    discrepancy_type: DiscrepancyType
    dataset_id: str
    observation_key: str
    sources: tuple[str, ...]
    severity: str
    explanation: str
    resolved: bool = False


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    compared_observations: int
    matching_observations: int
    findings: tuple[ReconciliationFinding, ...]
    automatic_overwrites: int = 0

    def __post_init__(self) -> None:
        if self.automatic_overwrites:
            raise ValueError("HTA reconciliation cannot overwrite source truth")


@dataclass(frozen=True, slots=True)
class DatasetCertification:
    dataset_id: str
    stage: HTAStage
    status: CertificationStatus
    active: bool
    checksum_score: Decimal
    parse_acceptance_score: Decimal
    completeness_score: Decimal
    consistency_score: Decimal
    reconciliation_score: Decimal
    overall_score: Decimal
    confidence: ConfidenceGrade
    reasons: tuple[str, ...]
    evidence: DatasetEvidence

    def __post_init__(self) -> None:
        if self.active != (self.status is CertificationStatus.PASS):
            raise ValueError("only PASS-certified HTA datasets may become ACTIVE")


@dataclass(frozen=True, slots=True)
class StageCertification:
    stage: HTAStage
    version: str
    status: CertificationStatus
    dataset_certifications: tuple[DatasetCertification, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicalDatasetScore:
    stage: HTAStage
    score: Decimal
    weight: Decimal
    certification: CertificationStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalTruthScorecard:
    scorecard_version: str
    logical_datasets: tuple[LogicalDatasetScore, ...]
    overall_score: Decimal
    target_score: Decimal
    target_met: bool
    confidence: ConfidenceGrade
    unknown_dataset_count: int


@dataclass(frozen=True, slots=True)
class WarehouseV2Candidate:
    version: str
    status: WarehouseCandidateStatus
    active_dataset_ids: tuple[str, ...]
    blocked_dataset_ids: tuple[str, ...]
    historical_truth_score: Decimal
    activation_performed: bool
    replay_migrated: bool
    production_influence: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        unsafe = (
            self.activation_performed
            or self.replay_migrated
            or self.production_influence
        )
        if unsafe:
            raise ValueError(
                "HTA candidate creation cannot affect production or replay"
            )


@dataclass(frozen=True, slots=True)
class StageRunResult:
    stage: HTAStage
    status: StageStatus
    attempted_datasets: tuple[str, ...]
    imported_files: int
    duplicate_files: int
    rejected_records: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionManifest:
    hta_version: str
    platform_version: str
    platform_manifest_hash: str
    generated_at: datetime
    requested_start: date | None
    requested_end: date | None
    selected_dataset: str | None
    resume_requested: bool
    verification_requested: bool
    force_requested: bool
    parallelism: int
    source_mode: str
    source_rights_basis: str
    stage_results: tuple[StageRunResult, ...]
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    production_influence: bool = PRODUCTION_INFLUENCE
    replay_migrated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        if self.parallelism < 1:
            raise ValueError("HTA parallelism must be positive")
        if self.production_influence or self.replay_migrated:
            raise ValueError("HTA acquisition cannot affect production or replay")
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )


@dataclass(frozen=True, slots=True)
class HTAResult:
    manifest: AcquisitionManifest
    certifications: tuple[StageCertification, ...]
    reconciliation: ReconciliationSummary
    scorecard: HistoricalTruthScorecard
    warehouse_candidate: WarehouseV2Candidate
    artifacts: tuple[Path, ...]


def stable_hash(value: object) -> str:
    return sha256(
        json.dumps(json_value(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(
            {item.name: getattr(value, item.name) for item in fields(value)}
        )
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime, Decimal, Path)):
        return str(value)
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [name for name in globals() if not name.startswith("_")]
