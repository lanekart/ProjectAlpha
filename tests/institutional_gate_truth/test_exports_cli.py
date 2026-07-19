from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.gate_truth_cli import gate_app
from alpha.institutional_gate_truth.exports import InstitutionalGateTruthExporter
from alpha.institutional_gate_truth.models import (
    NO_FEATURE_CHANGES,
    NO_GATE_CHANGES,
    NO_THRESHOLD_CHANGES,
    NO_WEIGHT_CHANGES,
    PRODUCTION_INFLUENCE,
    InstitutionalGateTruthReport,
)
from alpha.institutional_gate_truth.rendering import render_executive_report


def test_exports_are_deterministic_complete_and_immutable(
    tmp_path: Path,
    gate_report: InstitutionalGateTruthReport,
) -> None:
    exporter = InstitutionalGateTruthExporter()
    first = exporter.export(gate_report, output_directory=tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = exporter.export(gate_report, output_directory=tmp_path)
    assert first_bytes == {path.name: path.read_bytes() for path in second}
    assert len(first) == 11
    for name in (
        "rejected_population.csv",
        "rejection_classification.csv",
        "gate_effectiveness.csv",
        "reason_statistics.csv",
        "counterfactual_portfolio.csv",
        "false_rejections.csv",
        "executive_report.md",
        "manifest.json",
    ):
        assert (tmp_path / name).exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["production_influence"] is False
    assert manifest["no_gate_changes"] is True
    assert len(manifest["artifact_hashes"]) == 10
    rows = list(
        csv.DictReader(
            (tmp_path / "rejection_classification.csv").open(
                newline="", encoding="utf-8"
            )
        )
    )
    assert {row["classification"] for row in rows} == {
        "CORRECT_REJECTION",
        "FALSE_REJECTION",
    }


def test_cli_read_commands_and_rendering(
    tmp_path: Path,
    gate_report: InstitutionalGateTruthReport,
) -> None:
    InstitutionalGateTruthExporter().export(gate_report, output_directory=tmp_path)
    runner = CliRunner()
    rejected = runner.invoke(gate_app, ["rejected", "--output", str(tmp_path)])
    effectiveness = runner.invoke(
        gate_app, ["effectiveness", "--output", str(tmp_path)]
    )
    counterfactual = runner.invoke(
        gate_app, ["counterfactual", "--output", str(tmp_path)]
    )
    report = runner.invoke(gate_app, ["report", "--output", str(tmp_path)])
    assert rejected.exit_code == 0
    assert effectiveness.exit_code == 0
    assert counterfactual.exit_code == 0
    assert report.exit_code == 0
    assert "Rejected BUY Population" in rejected.stdout
    assert "Correct Rejections" in effectiveness.stdout
    assert "Gate-Off Counterfactual Portfolio" in counterfactual.stdout
    assert "Institutional Gate Truth Audit" in report.stdout
    rendered = render_executive_report(gate_report)
    assert "20D, 60D, and 120D" in rendered
    assert "UNAVAILABLE_IN_CABR_BASELINE" in rendered


def test_policy_isolation_constants_are_permanent() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert NO_GATE_CHANGES is True
    assert NO_WEIGHT_CHANGES is True
    assert NO_THRESHOLD_CHANGES is True
    assert NO_FEATURE_CHANGES is True
