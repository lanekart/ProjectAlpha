"""Base lifecycle for Project Alpha canonical recovery engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from .evidence_graph import EvidenceGraph
from .models import (
    CanonicalPreviewRow,
    EvidenceGraphSnapshot,
    RecoveryContext,
    RecoveryIssue,
    RecoveryResult,
)


class CanonicalRecoveryEngine(ABC):
    """Execute deterministic preview-only recovery through a fixed lifecycle."""

    engine_key: str
    engine_version: str

    def run(self, context: RecoveryContext) -> RecoveryResult:
        """Run discovery, evidence, validation, normalization and verification."""

        if context.engine_key != self.engine_key:
            raise ValueError(
                f"context engine_key {context.engine_key!r} does not match "
                f"engine {self.engine_key!r}"
            )
        discovery = self.discover(context)
        graph = self.build_evidence_graph(context, discovery)
        graph_snapshot = graph.snapshot()
        validation_issues = self.validate(context, discovery, graph_snapshot)
        normalized = self.normalize(
            context,
            discovery,
            graph_snapshot,
            validation_issues,
        )
        preview = self.recover(
            context,
            discovery,
            graph_snapshot,
            validation_issues,
            normalized,
        )
        verification_issues = self.verify(
            context,
            discovery,
            graph_snapshot,
            validation_issues,
            normalized,
            preview,
        )
        classification = self.classify(validation_issues, verification_issues)
        metadata = self.metadata(context, discovery, graph_snapshot, preview)
        return RecoveryResult(
            engine_key=self.engine_key,
            engine_version=self.engine_version,
            generated_at=context.as_of,
            classification=classification,
            discovery=discovery,
            evidence_graph=graph_snapshot,
            validation_issues=validation_issues,
            normalized=normalized,
            canonical_preview=preview,
            verification_issues=verification_issues,
            metadata=metadata,
        )

    @abstractmethod
    def discover(self, context: RecoveryContext) -> Mapping[str, object]:
        """Discover immutable raw evidence without modifying source data."""

    @abstractmethod
    def build_evidence_graph(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
    ) -> EvidenceGraph:
        """Build provenance relationships for discovered evidence."""

    @abstractmethod
    def validate(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
    ) -> tuple[RecoveryIssue, ...]:
        """Validate raw evidence before normalization."""

    @abstractmethod
    def normalize(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
    ) -> tuple[Mapping[str, object], ...]:
        """Normalize evidence into schema-compatible intermediate records."""

    @abstractmethod
    def recover(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
    ) -> tuple[CanonicalPreviewRow, ...]:
        """Produce canonical preview rows without writing canonical storage."""

    @abstractmethod
    def verify(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> tuple[RecoveryIssue, ...]:
        """Verify canonical preview integrity and provenance."""

    def classify(
        self,
        validation_issues: tuple[RecoveryIssue, ...],
        verification_issues: tuple[RecoveryIssue, ...],
    ) -> str:
        """Return a stable preview-readiness classification."""

        severities = {
            issue.severity.value
            for issue in validation_issues + verification_issues
        }
        if "CRITICAL" in severities or "HIGH" in severities:
            return "PREVIEW_BLOCKED"
        if severities:
            return "PREVIEW_WITH_WARNINGS"
        return "PREVIEW_READY"

    def metadata(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> Mapping[str, object]:
        """Return standard non-writing recovery metadata."""

        del context, discovery
        return {
            "preview_only": True,
            "canonical_writes": False,
            "evidence_node_count": len(graph.nodes),
            "evidence_edge_count": len(graph.edges),
            "preview_row_count": len(preview),
        }
