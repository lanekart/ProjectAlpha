"""Deterministic evidence graph for canonical recovery provenance."""

from __future__ import annotations

from .models import EvidenceEdge, EvidenceGraphSnapshot, EvidenceNode


class EvidenceGraph:
    """Build a duplicate-safe directed evidence graph."""

    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}
        self._edges: set[tuple[str, str, str]] = set()
        self._edge_values: list[EvidenceEdge] = []

    def add_node(self, node: EvidenceNode) -> None:
        """Add a unique node or reject conflicting duplicate identifiers."""

        existing = self._nodes.get(node.node_id)
        if existing is not None and existing != node:
            raise ValueError(f"conflicting evidence node {node.node_id!r}")
        self._nodes[node.node_id] = node

    def add_edge(self, edge: EvidenceEdge) -> None:
        """Add an edge after ensuring both endpoint nodes exist."""

        if edge.source_id not in self._nodes:
            raise ValueError(f"unknown source node {edge.source_id!r}")
        if edge.target_id not in self._nodes:
            raise ValueError(f"unknown target node {edge.target_id!r}")
        key = (edge.source_id, edge.relation, edge.target_id)
        if key in self._edges:
            return
        self._edges.add(key)
        self._edge_values.append(edge)

    def snapshot(self) -> EvidenceGraphSnapshot:
        """Return a stable immutable snapshot sorted by identifiers."""

        nodes = tuple(self._nodes[key] for key in sorted(self._nodes))
        edges = tuple(
            sorted(
                self._edge_values,
                key=lambda edge: (edge.source_id, edge.relation, edge.target_id),
            )
        )
        return EvidenceGraphSnapshot(nodes=nodes, edges=edges)
