from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path


class ArchiveDataset(StrEnum):
    BHAVCOPY = "bhavcopy"
    DELIVERY = "delivery"
    INDICES = "indices"
    VIX = "vix"
    CORPORATE_ACTIONS = "corporate_actions"
    SECURITY_MASTER = "security_master"
    HOLIDAYS = "holidays"


class ManifestStatus(StrEnum):
    PLANNED = "planned"
    DOWNLOADED = "downloaded"
    VALIDATED = "validated"
    INGESTED = "ingested"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ArchiveRequest:
    exchange: str
    dataset: ArchiveDataset
    trading_date: date
    source_url: str
    relative_path: Path


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    exchange: str
    dataset: ArchiveDataset
    trading_date: date
    source_url: str
    relative_path: str
    status: ManifestStatus
    retrieved_at: datetime | None = None
    sha256: str | None = None
    byte_size: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str
    row_number: int | None = None
