"""Orchestration facade for the diagnostic-only IRD subsystem."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from alpha.research.bottleneck_engine import BottleneckEngine
from alpha.research.briefing_engine import BriefingEngine
from alpha.research.diagnostic_registry import (
    DiagnosticRegistry,
    default_diagnostic_registry,
)
from alpha.research.engineering_roi import EngineeringRoiEngine
from alpha.research.models import (
    DiagnosticEvidence,
    EngineeringRoiReport,
    ExecutiveResearchBrief,
    InstitutionalResearchSnapshot,
    RankedBottleneck,
    RegisteredResearchExperiment,
    ResearchRoadmap,
)
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.research.roadmap_engine import RoadmapEngine


class InstitutionalResearchDirector:
    """Read-only research governance coordinator."""

    def __init__(
        self,
        *,
        diagnostic_registry: DiagnosticRegistry,
        experiment_registry: ResearchExperimentRegistry,
        bottleneck_engine: BottleneckEngine | None = None,
        roi_engine: EngineeringRoiEngine | None = None,
        roadmap_engine: RoadmapEngine | None = None,
        briefing_engine: BriefingEngine | None = None,
    ) -> None:
        self.diagnostic_registry = diagnostic_registry
        self.experiment_registry = experiment_registry
        self.bottleneck_engine = bottleneck_engine or BottleneckEngine()
        self.roi_engine = roi_engine or EngineeringRoiEngine()
        self.roadmap_engine = roadmap_engine or RoadmapEngine()
        self.briefing_engine = briefing_engine or BriefingEngine()

    @classmethod
    def from_default(
        cls,
        *,
        registry_path: Path | str | None = None,
        discover_plugins: bool = True,
    ) -> InstitutionalResearchDirector:
        return cls(
            diagnostic_registry=default_diagnostic_registry(
                discover_plugins=discover_plugins
            ),
            experiment_registry=ResearchExperimentRegistry(registry_path),
        )

    @cached_property
    def diagnostics(self) -> tuple[DiagnosticEvidence, ...]:
        return self.diagnostic_registry.collect()

    @cached_property
    def experiments(self) -> tuple[RegisteredResearchExperiment, ...]:
        return self.experiment_registry.load()

    @cached_property
    def bottlenecks(self) -> tuple[RankedBottleneck, ...]:
        return self.bottleneck_engine.rank(self.diagnostics)

    @cached_property
    def roi(self) -> EngineeringRoiReport:
        return self.roi_engine.assess(
            experiments=self.experiments,
            bottlenecks=self.bottlenecks,
        )

    @cached_property
    def roadmap(self) -> ResearchRoadmap:
        return self.roadmap_engine.generate(self.bottlenecks)

    @cached_property
    def briefing(self) -> ExecutiveResearchBrief:
        return self.briefing_engine.build(
            diagnostics=self.diagnostics,
            bottlenecks=self.bottlenecks,
            roadmap=self.roadmap,
            roi=self.roi,
        )

    def snapshot(self) -> InstitutionalResearchSnapshot:
        return InstitutionalResearchSnapshot(
            diagnostics=self.diagnostics,
            bottlenecks=self.bottlenecks,
            roadmap=self.roadmap,
            roi=self.roi,
            briefing=self.briefing,
        )


__all__ = ["InstitutionalResearchDirector"]
