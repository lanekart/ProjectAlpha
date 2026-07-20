"""Typed models shared by canonical recovery engines."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class EvidenceKind(StrEnum):
    """Supported evidence categories in the historical-truth graph."""

    RAW_FILE = "RAW_FILE"
    WAREHOUSE_TABLE = "WAREHOUSE_TABLE"
    SNAPSHOT = "SNAPSHOT"
    DERIVED = "DERIVED"
    GOVERNANCE = "GOVERNANCE"


class RecoverySeverity(StrEnum):
    """Severity assigned to validation or verification issues."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Immutable execution context supplied to a recovery engine."""

    engine_key: str
    as_of: datetime
    output_directory: Path | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    """One immutable evidence item supporting a canonical fact."""

    node_id: str
    kind: EvidenceKind
    source: str
    locator: str
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    """Directed relationship between evidence or canonical entities."""

    source_id: str
    relation: str
    target_id: str
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceGraphSnapshot:
    """Deterministic immutable graph snapshot."""

    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]


@dataclass(frozen=True, slots=True)
class RecoveryIssue:
    """Validation or verification issue detected during recovery."""

    issue_key: str
    severity: RecoverySeverity
    summary: str
    details: str = ""
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalPreviewRow:
    """Schema-neutral canonical preview row with source provenance."""

    record_key: str
    values: Mapping[str, object]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Complete output of one non-writing recovery lifecycle."""

    engine_key: str
    engine_version: str
    generated_at: datetime
    classification: str
    discovery: Mapping[str, object]
    evidence_graph: EvidenceGraphSnapshot
    validation_issues: tuple[RecoveryIssue, ...]
    normalized: tuple[Mapping[str, object], ...]
    canonical_preview: tuple[CanonicalPreviewRow, ...]
    verification_issues: tuple[RecoveryIssue, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
