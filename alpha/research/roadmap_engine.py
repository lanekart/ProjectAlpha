"""Rule-based IRD roadmap generation."""

from __future__ import annotations

from alpha.research.models import (
    RankedBottleneck,
    ResearchRoadmap,
    RoadmapItem,
    RoadmapPriority,
)


class RoadmapEngine:
    """Translate ranked diagnostic bottlenecks into traceable roadmap items."""

    def generate(
        self,
        bottlenecks: tuple[RankedBottleneck, ...],
    ) -> ResearchRoadmap:
        items = tuple(
            RoadmapItem(
                priority=item.priority,
                project_id=f"research-{item.bottleneck_id}",
                title=item.recommended_action,
                subsystem=item.subsystem,
                rationale=(
                    f"{item.status.value} diagnostic gap at "
                    f"{item.confidence.value} confidence: {item.evidence_summary}"
                ),
                supporting_diagnostics=item.supporting_diagnostics,
                dependencies=item.dependencies,
            )
            for item in bottlenecks
        )
        return ResearchRoadmap(items=items)


def first_actionable_item(roadmap: ResearchRoadmap) -> RoadmapItem | None:
    for priority in (
        RoadmapPriority.P0,
        RoadmapPriority.P1,
        RoadmapPriority.P2,
    ):
        items = roadmap.items_for(priority)
        if items:
            return items[0]
    return None


__all__ = ["RoadmapEngine", "first_actionable_item"]
