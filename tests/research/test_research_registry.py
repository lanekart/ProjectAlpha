from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.research.models import (
    ExperimentDecision,
    ExperimentStatus,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.research.research_registry import ResearchExperimentRegistry


def test_registry_insert_and_idempotent_duplicate_prevention(tmp_path: Path) -> None:
    registry = ResearchExperimentRegistry(tmp_path / "experiments.json")
    experiment = _experiment("exp-001")

    assert registry.record(experiment) is True
    assert registry.record(experiment) is False
    assert registry.load() == (experiment,)


def test_registry_rejects_conflicting_duplicate_id(tmp_path: Path) -> None:
    registry = ResearchExperimentRegistry(tmp_path / "experiments.json")
    experiment = _experiment("exp-001")
    registry.record(experiment)

    with pytest.raises(ValueError, match="different evidence"):
        registry.record(replace(experiment, title="Changed title"))


def test_json_export_is_deterministic_and_complete(tmp_path: Path) -> None:
    registry = ResearchExperimentRegistry(tmp_path / "experiments.json")
    registry.record(_experiment("exp-002"))
    registry.record(_experiment("exp-001"))
    destination = tmp_path / "export.json"

    registry.export_json(destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["production_influence"] is False
    assert [item["experiment_id"] for item in payload["experiments"]] == [
        "exp-001",
        "exp-002",
    ]
    first = payload["experiments"][0]
    assert first["purpose"] == "Measure a controlled treatment."
    assert first["baseline"][0]["source"] == "candidate replay"
    assert first["baseline"][0]["definition"] == "strict approval precision"
    assert first["baseline"][0]["population"] == "completed strict approvals"
    assert first["baseline"][0]["version"] == "approval-v1"


def test_csv_export_is_deterministic_and_complete(tmp_path: Path) -> None:
    registry = ResearchExperimentRegistry(tmp_path / "experiments.json")
    registry.record(_experiment("exp-001"))

    text = registry.csv_text()
    rows = tuple(csv.DictReader(io.StringIO(text)))

    assert len(rows) == 1
    assert rows[0]["experiment_id"] == "exp-001"
    assert rows[0]["production_influence"] == "false"
    assert "strict approval precision" in rows[0]["baseline"]


def test_registry_rejects_production_influence(tmp_path: Path) -> None:
    path = tmp_path / "experiments.json"
    path.write_text(
        '{"experiments": [], "production_influence": true}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="production influence must be false"):
        ResearchExperimentRegistry(path).load()


def _experiment(experiment_id: str) -> RegisteredResearchExperiment:
    provenance = MetricProvenance(
        source="candidate replay",
        definition="strict approval precision",
        population="completed strict approvals",
        version="approval-v1",
    )
    baseline = ResearchMetric(
        metric_id="approval.precision",
        label="Approval precision",
        value=Decimal("0.40"),
        unit="ratio",
        provenance=provenance,
    )
    treatment = replace(baseline, value=Decimal("0.45"))
    return RegisteredResearchExperiment(
        experiment_id=experiment_id,
        title="Approval experiment",
        subsystem=ResearchSubsystem.APPROVAL,
        experiment_date=date(2026, 7, 18),
        purpose="Measure a controlled treatment.",
        evidence_sources=("candidate replay",),
        baseline=(baseline,),
        treatment=(treatment,),
        metrics=("approval.precision",),
        statistical_confidence=ResearchConfidence.MEDIUM,
        decision=ExperimentDecision.INCONCLUSIVE,
        status=ExperimentStatus.COMPLETED,
    )
