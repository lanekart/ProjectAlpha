from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.research.diagnostic_registry import (
    CallableDiagnosticPlugin,
    DiagnosticRegistry,
)
from alpha.research.institutional_research_director import (
    InstitutionalResearchDirector,
)
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.research.research_registry import ResearchExperimentRegistry

runner = CliRunner()


def test_all_ird_cli_commands_render_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    director = _director(tmp_path)
    _patch_default_director(monkeypatch, director)

    bottlenecks = runner.invoke(app, ["research", "bottlenecks"])
    roadmap = runner.invoke(app, ["research", "roadmap"])
    roi = runner.invoke(app, ["research", "roi"])
    registry = runner.invoke(app, ["research", "registry"])
    briefing = runner.invoke(app, ["research", "briefing"])

    assert bottlenecks.exit_code == 0
    assert "Institutional Research Director - Bottlenecks" in bottlenecks.stdout
    assert "Supporting Diagnostics: replay-readiness" in bottlenecks.stdout
    assert roadmap.exit_code == 0
    assert "Institutional Research Director - Evidence Roadmap" in roadmap.stdout
    assert "P1" in roadmap.stdout
    assert roi.exit_code == 0
    assert "Measured ROI" in roi.stdout
    assert "Estimated ROI" in roi.stdout
    assert registry.exit_code == 0
    assert "Diagnostic Registry (1)" in registry.stdout
    assert "Research Experiment Registry (0)" in registry.stdout
    assert briefing.exit_code == 0
    assert "Executive Research Brief" in briefing.stdout
    assert "Current Replay Readiness: 57.50% (889/1546)" in briefing.stdout
    for result in (bottlenecks, roadmap, roi, registry, briefing):
        assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_registry_cli_supports_json_csv_and_file_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    director = _director(tmp_path)
    _patch_default_director(monkeypatch, director)
    destination = tmp_path / "registry.csv"

    json_result = runner.invoke(app, ["research", "registry", "--format", "json"])
    csv_result = runner.invoke(app, ["research", "registry", "--format", "csv"])
    export_result = runner.invoke(
        app,
        [
            "research",
            "registry",
            "--format",
            "csv",
            "--output",
            str(destination),
        ],
    )

    assert json_result.exit_code == 0
    assert '"production_influence": false' in json_result.stdout
    assert csv_result.exit_code == 0
    assert csv_result.stdout.startswith("experiment_id,title,subsystem")
    assert export_result.exit_code == 0
    assert destination.exists()


def _director(tmp_path: Path) -> InstitutionalResearchDirector:
    evidence = DiagnosticEvidence(
        diagnostic_id="replay-readiness",
        title="Replay readiness",
        subsystem=ResearchSubsystem.REPLAY_READINESS,
        source_module="tests.replay",
        source_version="v1",
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=ResearchConfidence.HIGH,
        bottleneck_status=BottleneckStatus.PROVEN,
        metrics=(
            _metric("replay.readiness", Decimal("0.5750"), "ratio"),
            _metric("replay.ready_records", 889, "count"),
            _metric("replay.total_candidates", 1546, "count"),
        ),
        finding="889 of 1546 records are ready.",
        recommended_action="Acquire authoritative history.",
        dependencies=("authoritative historical prices",),
    )
    registry = DiagnosticRegistry()
    registry.register(
        CallableDiagnosticPlugin(
            diagnostic_id=evidence.diagnostic_id,
            title=evidence.title,
            subsystem=evidence.subsystem,
            source_module=evidence.source_module,
            collector=lambda: evidence,
        )
    )
    return InstitutionalResearchDirector(
        diagnostic_registry=registry,
        experiment_registry=ResearchExperimentRegistry(
            tmp_path / "experiment_registry.json"
        ),
    )


def _metric(
    metric_id: str,
    value: Decimal | int,
    unit: str,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=metric_id,
        value=value,
        unit=unit,
        provenance=MetricProvenance(
            source="test replay",
            definition=metric_id,
            population="test population",
            version="test-v1",
        ),
    )


def _patch_default_director(
    monkeypatch: pytest.MonkeyPatch,
    director: InstitutionalResearchDirector,
) -> None:
    def from_default(
        cls: type[InstitutionalResearchDirector],
        **_: object,
    ) -> InstitutionalResearchDirector:
        del cls
        return director

    monkeypatch.setattr(
        InstitutionalResearchDirector,
        "from_default",
        classmethod(from_default),
    )
