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
from .security_entity import (
    SecurityEntityRecoveryEngine,
    export_security_entity_recovery,
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
    "SecurityEntityRecoveryEngine",
    "SourceSchema",
    "discover_sources",
    "export_schema_discovery",
    "export_security_entity_recovery",
    "registry",
]
