"""Corporate-action lineage and point-in-time validity checks."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from alpha.point_in_time_universe.models import (
    CorporateActionRecord,
    EvidenceStatus,
)


class CorporateActionHistory:
    def __init__(
        self,
        records: tuple[CorporateActionRecord, ...] = (),
        *,
        evidence_complete_through: date | None = None,
    ) -> None:
        self.records = tuple(
            sorted(records, key=lambda item: (item.effective_date, item.action_id))
        )
        self.evidence_complete_through = evidence_complete_through
        if len({item.action_id for item in self.records}) != len(self.records):
            raise ValueError("corporate action ids must be unique")
        self._validate_lineage_cycles()

    def actions_for(
        self, security_id: str, *, through: date | None = None
    ) -> tuple[CorporateActionRecord, ...]:
        return tuple(
            item
            for item in self.records
            if item.security_id == security_id
            and (through is None or item.effective_date <= through)
        )

    def validity(self, as_of: date) -> EvidenceStatus:
        if self.evidence_complete_through is None:
            return EvidenceStatus.UNKNOWN
        return (
            EvidenceStatus.KNOWN
            if as_of <= self.evidence_complete_through
            else EvidenceStatus.PARTIAL
        )

    def lineage(self, security_id: str) -> tuple[str, ...]:
        related = {security_id}
        changed = True
        while changed:
            changed = False
            for action in self.records:
                participants = {
                    action.security_id,
                    *action.predecessor_security_ids,
                    *action.successor_security_ids,
                }
                if related.intersection(participants) and not participants <= related:
                    related.update(participants)
                    changed = True
        return tuple(sorted(related))

    def _validate_lineage_cycles(self) -> None:
        graph: dict[str, set[str]] = defaultdict(set)
        for action in self.records:
            predecessors = action.predecessor_security_ids or (action.security_id,)
            for predecessor in predecessors:
                graph[predecessor].update(action.successor_security_ids)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("corporate action lineage contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for successor in graph.get(node, ()):
                visit(successor)
            visiting.remove(node)
            visited.add(node)

        for node in tuple(graph):
            visit(node)


__all__ = ["CorporateActionHistory"]
