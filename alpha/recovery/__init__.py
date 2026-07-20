"""Canonical recovery foundation for Project Alpha."""

from .base import CanonicalRecoveryEngine
from .evidence_graph import EvidenceGraph
from .models import (
    CanonicalPreviewRow,
    EvidenceEdge,
    EvidenceGraphSnapshot,
    EvidenceKind,
    EvidenceNode,
    RecoveryContext,
    RecoveryIssue,
    RecoveryResult,
    RecoverySeverity,
)
from .registry import RecoveryRegistry, registry
from .schema_discovery import (
    FieldProfile,
    MappingCandidate,
    SchemaDiscoveryResult,
    SourceSchema,
    discover_sources,
    export_schema_discovery,
)

__all__ = [
    "CanonicalPreviewRow",
    "CanonicalRecoveryEngine",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceGraphSnapshot",
    "EvidenceKind",
    "EvidenceNode",
    "FieldProfile",
    "MappingCandidate",
    "RecoveryContext",
    "RecoveryIssue",
    "RecoveryRegistry",
    "RecoveryResult",
    "RecoverySeverity",
    "SchemaDiscoveryResult",
    "SourceSchema",
    "discover_sources",
    "export_schema_discovery",
    "registry",
]
