from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.gate_dependency_cli import gate_dependency_app
from alpha.gate_dependency_audit.exports import GateDependencyAuditExporter
from alpha.gate_dependency_audit.models import (
    NO_GATE_CHANGES,
    NO_ORDER_CHANGES,
    NO_THRESHOLD_CHANGES,
    PRODUCTION_INFLUENCE,
    GateDependencyAuditReport,
)
from alpha.gate_dependency_audit.rendering import render_executive_report


def test_exports_are_complete_deterministic_and_immutable(
    tmp_path: Path,
    dependency_report: GateDependencyAuditReport,
) -> None:
    exporter = GateDependencyAuditExporter()
    first = exporter.export(dependency_report, output_directory=tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = exporter.export(dependency_report, output_directory=tmp_path)
    assert first_bytes == {path.name: path.read_bytes() for path in second}
    assert len(first) == 12
    for name in (
        "gate_lineage.csv",
        "first_failure.csv",
        "gate_survival.csv",
        "dependency_matrix.csv",
        "interaction_matrix.csv",
        "marginal_value.csv",
        "false_rejection_paths.csv",
        "correct_rejection_paths.csv",
        "gate_report_card.csv",
        "executive_report.md",
        "manifest.json",
    ):
        assert (tmp_path / name).exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["production_influence"] is False
    assert len(manifest["artifact_hashes"]) == 11
    rows = list(
        csv.DictReader(
            (tmp_path / "gate_lineage.csv").open(newline="", encoding="utf-8")
        )
    )
    assert len(rows) == len(dependency_report.lineages) * 20
    assert {row["observed_status"] for row in rows} >= {"PASS", "FAIL"}


def test_cli_read_commands_and_rendering(
    tmp_path: Path,
    dependency_report: GateDependencyAuditReport,
) -> None:
    GateDependencyAuditExporter().export(
        dependency_report,
        output_directory=tmp_path,
    )
    runner = CliRunner()
    survival = runner.invoke(
        gate_dependency_app,
        ["survival", "--output", str(tmp_path)],
    )
    interactions = runner.invoke(
        gate_dependency_app,
        ["interactions", "--output", str(tmp_path)],
    )
    report = runner.invoke(
        gate_dependency_app,
        ["report", "--output", str(tmp_path)],
    )
    assert survival.exit_code == 0
    assert interactions.exit_code == 0
    assert report.exit_code == 0
    assert "Gate Sequential Survival" in survival.stdout
    assert "Gate Interaction Matrix" in interactions.stdout
    assert "Gate Dependency & Sequential Bottleneck Audit" in report.stdout
    rendered = render_executive_report(dependency_report)
    assert "## Bottleneck Flow" in rendered
    assert "full observed failure set" in rendered
    assert "Largest sequential false-rejection blocker" in rendered


def test_policy_isolation_constants_are_permanent() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert NO_GATE_CHANGES is True
    assert NO_ORDER_CHANGES is True
    assert NO_THRESHOLD_CHANGES is True
