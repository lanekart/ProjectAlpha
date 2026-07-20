"""Deterministic tests for the canonical recovery foundation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha.recovery import (
    CanonicalPreviewRow,
    CanonicalRecoveryEngine,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceGraphSnapshot,
    EvidenceKind,
    EvidenceNode,
    RecoveryContext,
    RecoveryIssue,
    RecoveryRegistry,
    RecoverySeverity,
)


class ExampleRecoveryEngine(CanonicalRecoveryEngine):
    engine_key = "example-recovery"
    engine_version = "1.0.0"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def discover(self, context: RecoveryContext) -> Mapping[str, object]:
        self.calls.append("discover")
        return {"source": context.parameters["source"]}

    def build_evidence_graph(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
    ) -> EvidenceGraph:
        del context
        self.calls.append("build_evidence_graph")
        graph = EvidenceGraph()
        graph.add_node(
            EvidenceNode(
                node_id="raw:1",
                kind=EvidenceKind.RAW_FILE,
                source=str(discovery["source"]),
                locator="row:1",
            )
        )
        graph.add_node(
            EvidenceNode(
                node_id="entity:1",
                kind=EvidenceKind.DERIVED,
                source="example-recovery",
                locator="entity:1",
            )
        )
        graph.add_edge(EvidenceEdge("raw:1", "SUPPORTS", "entity:1"))
        return graph

    def validate(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
    ) -> tuple[RecoveryIssue, ...]:
        del context, discovery, graph
        self.calls.append("validate")
        return ()

    def normalize(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
    ) -> tuple[Mapping[str, object], ...]:
        del context, discovery, graph, validation_issues
        self.calls.append("normalize")
        return ({"security_id": "entity:1", "symbol": "ABC"},)

    def recover(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
    ) -> tuple[CanonicalPreviewRow, ...]:
        del context, discovery, graph, validation_issues
        self.calls.append("recover")
        return (
            CanonicalPreviewRow(
                record_key="entity:1",
                values=normalized[0],
                evidence_ids=("raw:1",),
            ),
        )

    def verify(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> tuple[RecoveryIssue, ...]:
        del context, discovery, graph, validation_issues, normalized, preview
        self.calls.append("verify")
        return ()


def _context(tmp_path: Path) -> RecoveryContext:
    return RecoveryContext(
        engine_key="example-recovery",
        as_of=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        output_directory=tmp_path,
        parameters={"source": "security_master.json"},
    )


def test_recovery_lifecycle_is_fixed_and_preview_only(tmp_path: Path) -> None:
    engine = ExampleRecoveryEngine()

    result = engine.run(_context(tmp_path))

    assert engine.calls == [
        "discover",
        "build_evidence_graph",
        "validate",
        "normalize",
        "recover",
        "verify",
    ]
    assert result.classification == "PREVIEW_READY"
    assert result.metadata["preview_only"] is True
    assert result.metadata["canonical_writes"] is False
    assert result.canonical_preview[0].record_key == "entity:1"


def test_evidence_graph_is_deterministic_and_duplicate_safe() -> None:
    graph = EvidenceGraph()
    node_b = EvidenceNode("b", EvidenceKind.DERIVED, "test", "b")
    node_a = EvidenceNode("a", EvidenceKind.RAW_FILE, "test", "a")
    graph.add_node(node_b)
    graph.add_node(node_a)
    graph.add_edge(EvidenceEdge("a", "SUPPORTS", "b"))
    graph.add_edge(EvidenceEdge("a", "SUPPORTS", "b"))

    snapshot = graph.snapshot()

    assert tuple(node.node_id for node in snapshot.nodes) == ("a", "b")
    assert len(snapshot.edges) == 1
    with pytest.raises(ValueError, match="conflicting evidence node"):
        graph.add_node(EvidenceNode("a", EvidenceKind.SNAPSHOT, "other", "a"))


def test_evidence_graph_rejects_orphan_edges() -> None:
    graph = EvidenceGraph()
    graph.add_node(EvidenceNode("a", EvidenceKind.RAW_FILE, "test", "a"))

    with pytest.raises(ValueError, match="unknown target node"):
        graph.add_edge(EvidenceEdge("a", "SUPPORTS", "missing"))


def test_recovery_classification_respects_issue_severity() -> None:
    engine = ExampleRecoveryEngine()
    warning = RecoveryIssue(
        issue_key="warning",
        severity=RecoverySeverity.MEDIUM,
        summary="Warning",
    )
    blocker = RecoveryIssue(
        issue_key="blocker",
        severity=RecoverySeverity.HIGH,
        summary="Blocker",
    )

    assert engine.classify((warning,), ()) == "PREVIEW_WITH_WARNINGS"
    assert engine.classify((blocker,), ()) == "PREVIEW_BLOCKED"


def test_recovery_registry_rejects_duplicates_and_bad_factories() -> None:
    registry = RecoveryRegistry()
    registry.register("example-recovery", ExampleRecoveryEngine)

    assert registry.keys() == ("example-recovery",)
    assert isinstance(registry.create("example-recovery"), ExampleRecoveryEngine)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("example-recovery", ExampleRecoveryEngine)

    registry.register("alias", ExampleRecoveryEngine)
    with pytest.raises(ValueError, match="produced engine"):
        registry.create("alias")
