from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from alpha.research.bottleneck_engine import BottleneckEngine
from alpha.research.briefing_engine import BriefingEngine
from alpha.research.diagnostic_registry import (
    CallableDiagnosticPlugin,
    DiagnosticRegistry,
    default_diagnostic_registry,
)
from alpha.research.engineering_roi import EngineeringRoiEngine
from alpha.research.institutional_research_director import (
    InstitutionalResearchDirector,
)
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    ExperimentDecision,
    ExperimentStatus,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
    RoadmapPriority,
)
from alpha.research.rendering import (
    render_bottlenecks,
    render_briefing,
    render_registry,
    render_roadmap,
    render_roi,
)
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.research.roadmap_engine import RoadmapEngine


def test_default_registry_registers_existing_diagnostics() -> None:
    registry = default_diagnostic_registry(discover_plugins=False)

    assert registry.plugin_ids == (
        "adaptive-indicator-weight-research",
        "approval-diagnostics",
        "autonomous-decision-evidence-loop",
        "candidate-generation-recovery-audit",
        "canonical-runtime-parity-opportunity-audit",
        "canonical-universe-opportunity-audit",
        "continuous-learning-evidence",
        "corporate-action-coverage",
        "directional-signal-audit",
        "entry-timing-audit",
        "identity-coverage",
        "market-dna-discovery",
        "market-regime-audit",
        "market-truth-engine",
        "point-in-time-audit",
        "point-in-time-feature-attribution",
        "replay-readiness",
        "setup-discovery-evidence",
        "strategy-discovery-generalisation",
        "strategy-indicator-backtest-lab",
    )


def test_plugin_registry_is_deterministic_and_rejects_duplicates() -> None:
    registry = DiagnosticRegistry()
    second = _plugin("second", _evidence("second"))
    first = _plugin("first", _evidence("first"))

    registry.register(second)
    registry.register(first)

    assert tuple(item.diagnostic_id for item in registry.collect()) == (
        "first",
        "second",
    )
    with pytest.raises(ValueError, match="diagnostic already registered"):
        registry.register(first)


def test_plugin_failure_becomes_unknown_evidence() -> None:
    registry = DiagnosticRegistry()
    registry.register(
        CallableDiagnosticPlugin(
            diagnostic_id="failure",
            title="Failure",
            subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
            source_module="tests.failure",
            collector=_raise_runtime_error,
        )
    )

    evidence = registry.collect()[0]

    assert evidence.state is DiagnosticState.FAILED
    assert evidence.bottleneck_status is BottleneckStatus.UNKNOWN
    assert evidence.metrics == ()
    assert evidence.production_influence is False


def test_future_plugin_registers_through_module_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = _plugin("future", _evidence("future"))
    module = SimpleNamespace(RESEARCH_DIAGNOSTIC_PLUGIN=plugin)
    monkeypatch.setattr(
        "alpha.research.diagnostic_registry.importlib.import_module",
        lambda _: module,
    )
    registry = DiagnosticRegistry()

    count = registry.register_module("future.diagnostic")

    assert count == 1
    assert registry.plugin_ids == ("future",)


def test_metric_comparison_requires_identical_lineage() -> None:
    baseline = _metric("precision", Decimal("0.40"))
    changed_definition = replace(
        baseline,
        value=Decimal("0.50"),
        provenance=replace(
            baseline.provenance,
            definition="a different approval definition",
        ),
    )

    assert baseline.comparable_with(replace(baseline, value=Decimal("0.50")))
    assert not baseline.comparable_with(changed_definition)


def test_bottleneck_ranking_uses_evidence_rules() -> None:
    p1 = _evidence(
        "partial",
        maturity=ResearchMaturity.PARTIAL,
        confidence=ResearchConfidence.MEDIUM,
    )
    deferred = _evidence(
        "unknown",
        maturity=ResearchMaturity.UNKNOWN,
        confidence=ResearchConfidence.UNKNOWN,
        status=BottleneckStatus.UNKNOWN,
    )
    p0 = _evidence(
        "blocked",
        maturity=ResearchMaturity.BLOCKED,
        confidence=ResearchConfidence.HIGH,
    )

    report = BottleneckEngine().rank((p1, deferred, p0))

    assert tuple(item.bottleneck_id for item in report) == (
        "blocked-bottleneck",
        "partial-bottleneck",
        "unknown-bottleneck",
    )
    assert tuple(item.priority for item in report) == (
        RoadmapPriority.P0,
        RoadmapPriority.P1,
        RoadmapPriority.DEFERRED,
    )


def test_roadmap_references_supporting_diagnostics() -> None:
    bottlenecks = BottleneckEngine().rank((_evidence("approval"),))

    roadmap = RoadmapEngine().generate(bottlenecks)

    assert roadmap.items[0].supporting_diagnostics == ("approval",)
    assert roadmap.items[0].priority is RoadmapPriority.P1
    assert roadmap.production_influence is False


def test_engineering_roi_uses_only_completed_comparable_experiments() -> None:
    completed = _experiment("completed")
    planned = replace(
        completed, experiment_id="planned", status=ExperimentStatus.PLANNED
    )
    bottlenecks = BottleneckEngine().rank((_evidence("approval"),))

    report = EngineeringRoiEngine().assess(
        experiments=(planned, completed),
        bottlenecks=bottlenecks,
    )

    assert report.completed_experiments == 1
    assert len(report.measured) == 1
    assert report.measured[0].absolute_change == Decimal("0.10")
    assert report.estimated[0].estimated_gain is None
    assert report.estimated[0].confidence is ResearchConfidence.UNKNOWN


def test_engineering_roi_rejects_definition_incompatible_delta() -> None:
    experiment = _experiment("incompatible")
    incompatible = replace(
        experiment,
        treatment=(
            replace(
                experiment.treatment[0],
                provenance=replace(
                    experiment.treatment[0].provenance,
                    population="a different population",
                ),
            ),
        ),
    )

    report = EngineeringRoiEngine().assess(
        experiments=(incompatible,),
        bottlenecks=(),
    )

    assert report.measured == ()


def test_briefing_reports_readiness_and_unknown_roi() -> None:
    replay = _evidence(
        "replay-readiness",
        metrics=(
            _metric("replay.readiness", Decimal("0.5750")),
            _metric("replay.ready_records", 889, unit="count"),
            _metric("replay.total_candidates", 1546, unit="count"),
        ),
    )
    bottlenecks = BottleneckEngine().rank((replay,))
    roadmap = RoadmapEngine().generate(bottlenecks)
    roi = EngineeringRoiEngine().assess(experiments=(), bottlenecks=bottlenecks)

    brief = BriefingEngine().build(
        diagnostics=(replay,),
        bottlenecks=bottlenecks,
        roadmap=roadmap,
        roi=roi,
    )

    assert brief.current_replay_readiness == "57.50% (889/1546)"
    assert brief.highest_roi_completed_project == "Unavailable"
    assert tuple(item.metric_id for item in brief.initial_evidence) == (
        "replay.readiness",
    )
    assert brief.production_influence is False


def test_director_snapshot_remains_diagnostic_only(tmp_path: Path) -> None:
    registry = DiagnosticRegistry()
    registry.register(_plugin("approval", _evidence("approval")))
    director = InstitutionalResearchDirector(
        diagnostic_registry=registry,
        experiment_registry=ResearchExperimentRegistry(tmp_path / "registry.json"),
    )

    snapshot = director.snapshot()

    assert snapshot.production_influence is False
    assert all(not item.production_influence for item in snapshot.diagnostics)
    assert all(not item.production_influence for item in snapshot.bottlenecks)
    assert all(not item.production_influence for item in snapshot.roadmap.items)
    with pytest.raises(ValueError, match="cannot influence production"):
        replace(snapshot.diagnostics[0], production_influence=True)


def test_renderers_are_deterministic_and_explain_lineage(tmp_path: Path) -> None:
    evidence = (_evidence("approval"),)
    bottlenecks = BottleneckEngine().rank(evidence)
    roadmap = RoadmapEngine().generate(bottlenecks)
    roi = EngineeringRoiEngine().assess(experiments=(), bottlenecks=bottlenecks)
    brief = BriefingEngine().build(
        diagnostics=evidence,
        bottlenecks=bottlenecks,
        roadmap=roadmap,
        roi=roi,
    )
    experiment = _experiment("exp-1")

    assert "Supporting Diagnostics: approval" in render_bottlenecks(bottlenecks)
    assert "P1" in render_roadmap(roadmap)
    assert "Estimated values are not measured" in render_roi(roi)
    registry_text = render_registry(diagnostics=evidence, experiments=(experiment,))
    assert "Metric Provenance Contract" in registry_text
    assert "Definition-incompatible metrics are never compared" in registry_text
    assert "Current Replay Readiness" in render_briefing(brief)
    assert not (tmp_path / "unused").exists()


def test_ird_documentation_describes_constraints() -> None:
    path = Path("docs/institutional_research_director.md")

    text = path.read_text(encoding="utf-8")

    assert "PRODUCTION_INFLUENCE=false" in text
    assert "Diagnostic Registration" in text
    assert "Experiment Registry" in text
    assert "Priority Rules" in text
    assert "Definition-incompatible metrics are never compared" in text


def _plugin(
    diagnostic_id: str,
    evidence: DiagnosticEvidence,
) -> CallableDiagnosticPlugin:
    return CallableDiagnosticPlugin(
        diagnostic_id=diagnostic_id,
        title=evidence.title,
        subsystem=evidence.subsystem,
        source_module=evidence.source_module,
        collector=lambda: evidence,
    )


def _evidence(
    diagnostic_id: str,
    *,
    maturity: ResearchMaturity = ResearchMaturity.PARTIAL,
    confidence: ResearchConfidence = ResearchConfidence.HIGH,
    status: BottleneckStatus = BottleneckStatus.PROVEN,
    metrics: tuple[ResearchMetric, ...] | None = None,
) -> DiagnosticEvidence:
    return DiagnosticEvidence(
        diagnostic_id=diagnostic_id,
        title=f"{diagnostic_id} title",
        subsystem=ResearchSubsystem.APPROVAL,
        source_module=f"tests.{diagnostic_id}",
        source_version="v1",
        state=DiagnosticState.AVAILABLE,
        maturity=maturity,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=confidence,
        bottleneck_status=status,
        metrics=(
            metrics if metrics is not None else (_metric("sample", 100, unit="count"),)
        ),
        finding=f"{diagnostic_id} finding",
        recommended_action=f"Investigate {diagnostic_id}",
        dependencies=("candidate ledger",),
    )


def _metric(
    metric_id: str,
    value: Decimal | int,
    *,
    unit: str = "ratio",
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=metric_id,
        value=value,
        unit=unit,
        provenance=MetricProvenance(
            source="test source",
            definition="test definition",
            population="test population",
            version="test-v1",
        ),
    )


def _experiment(experiment_id: str) -> RegisteredResearchExperiment:
    baseline = _metric("precision", Decimal("0.40"))
    treatment = replace(baseline, value=Decimal("0.50"))
    return RegisteredResearchExperiment(
        experiment_id=experiment_id,
        title="Approval precision experiment",
        subsystem=ResearchSubsystem.APPROVAL,
        experiment_date=date(2026, 7, 18),
        purpose="Measure an isolated approval policy treatment.",
        evidence_sources=("candidate ledger",),
        baseline=(baseline,),
        treatment=(treatment,),
        metrics=("precision",),
        statistical_confidence=ResearchConfidence.MEDIUM,
        decision=ExperimentDecision.INCONCLUSIVE,
        status=ExperimentStatus.COMPLETED,
    )


def _raise_runtime_error() -> DiagnosticEvidence:
    raise RuntimeError("expected test failure")
