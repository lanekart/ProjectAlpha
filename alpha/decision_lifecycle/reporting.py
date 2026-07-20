from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from io import StringIO

from alpha.decision_lifecycle.lifecycle import (
    LifecycleRecord,
    LifecycleState,
    LifecycleTransition,
)


@dataclass(frozen=True, slots=True)
class LifecycleSummary:
    total_records: int
    counts: tuple[tuple[LifecycleState, int], ...]
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.total_records < 0:
            raise ValueError("total_records cannot be negative")
        if self.production_influence:
            raise ValueError("lifecycle summary cannot influence production execution")
        normalized = tuple(
            (LifecycleState(state), count) for state, count in self.counts
        )
        if any(count < 0 for _, count in normalized):
            raise ValueError("lifecycle summary counts cannot be negative")
        if sum(count for _, count in normalized) != self.total_records:
            raise ValueError("lifecycle summary counts must reconcile to total_records")
        object.__setattr__(self, "counts", normalized)

    def count(self, state: LifecycleState) -> int:
        state = LifecycleState(state)
        return dict(self.counts).get(state, 0)


def build_lifecycle_summary(records: Iterable[LifecycleRecord]) -> LifecycleSummary:
    materialized = tuple(records)
    counter = Counter(record.current_state for record in materialized)
    counts = tuple((state, counter.get(state, 0)) for state in LifecycleState)
    return LifecycleSummary(total_records=len(materialized), counts=counts)


def render_lifecycle_summary(summary: LifecycleSummary) -> tuple[str, ...]:
    lines = [
        "Decision Lifecycle Summary",
        f"Total Opportunities: {summary.total_records}",
    ]
    lines.extend(f"{state.value}: {count}" for state, count in summary.counts)
    lines.append("Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE")
    return tuple(lines)


def export_history_csv(events: Iterable[LifecycleTransition]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "recommendation_id",
            "symbol",
            "occurred_at",
            "previous_state",
            "new_state",
            "reason",
            "confidence",
            "reduction_percent",
            "evidence_codes",
            "evidence_details",
            "production_influence",
        )
    )
    for event in events:
        writer.writerow(
            (
                event.recommendation_id,
                event.symbol,
                event.occurred_at.isoformat(),
                event.previous_state.value,
                event.new_state.value,
                event.reason,
                event.confidence.value,
                "" if event.reduction_percent is None else event.reduction_percent,
                "|".join(item.code for item in event.evidence),
                "|".join(item.detail for item in event.evidence),
                str(event.production_influence).lower(),
            )
        )
    return output.getvalue()
