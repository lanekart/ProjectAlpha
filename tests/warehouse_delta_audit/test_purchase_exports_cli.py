from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.warehouse_delta_cli import warehouse_delta_app
from alpha.warehouse_delta_audit.engine import WarehouseDeltaAuditEngine
from alpha.warehouse_delta_audit.exports import WarehouseDeltaExporter
from alpha.warehouse_delta_audit.models import (
    DecisionDeltaRecord,
    DecisionSeverity,
    PersonalDecision,
    PriceDeltaRecord,
    PurchaseRecommendation,
    ReplayDeltaRecord,
    SourceLineage,
    WarehouseDeltaReport,
)
from alpha.warehouse_delta_audit.purchase import purchase_decision
from alpha.warehouse_delta_audit.rendering import render_purchase_justification


def _price() -> tuple[PriceDeltaRecord, ...]:
    return (
        PriceDeltaRecord(
            "TEST",
            1500,
            1490,
            5,
            5,
            0,
            0,
            0,
            0,
            5,
            5,
            5,
            5,
            5,
            Decimal("0.01"),
            Decimal("0.02"),
        ),
    )


def _decision() -> tuple[DecisionDeltaRecord, ...]:
    return (
        DecisionDeltaRecord(
            date(2025, 1, 2),
            "TEST",
            Decimal("65"),
            Decimal("80"),
            False,
            True,
            "REJECTED",
            "APPROVED",
            DecisionSeverity.MATERIAL,
            "Approval changed.",
        ),
    )


def _replay() -> tuple[ReplayDeltaRecord, ...]:
    return (
        ReplayDeltaRecord(
            "expectancy",
            Decimal("0.1"),
            Decimal("0.5"),
            Decimal("0.4"),
            "percent",
            "improved",
        ),
        ReplayDeltaRecord(
            "maximum_drawdown",
            Decimal("10"),
            Decimal("8"),
            Decimal("-2"),
            "percent",
            "improved",
        ),
        ReplayDeltaRecord(
            "opportunity_capture",
            Decimal("5"),
            Decimal("8"),
            Decimal("3"),
            "percent",
            "improved",
        ),
    )


def test_same_lineage_control_never_claims_purchase_uplift() -> None:
    result = purchase_decision(
        source_lineage=SourceLineage.LEGACY_LINEAGE_RAW_SOURCE,
        prices=_price(),
        decisions=_decision(),
        replay=_replay(),
        corporate_actions_available=False,
        spans_five_years=True,
    )
    assert result[0] is PurchaseRecommendation.PURCHASE_NOT_JUSTIFIED
    assert result[1] is PersonalDecision.NOT_YET
    assert "UNKNOWN" in result[4]
    assert "same-lineage" in result[5]


def test_independent_positive_replay_can_justify_purchase() -> None:
    result = purchase_decision(
        source_lineage=SourceLineage.INDEPENDENT_OFFICIAL,
        prices=_price(),
        decisions=_decision(),
        replay=_replay(),
        corporate_actions_available=False,
        spans_five_years=True,
    )
    assert result[0] is PurchaseRecommendation.PURCHASE_JUSTIFIED
    assert result[1] is PersonalDecision.YES


def test_exports_are_complete_deterministic_and_answer_personal_question(
    tmp_path: Path,
    warehouse_delta_report: WarehouseDeltaReport,
) -> None:
    exporter = WarehouseDeltaExporter()
    first = exporter.export(warehouse_delta_report, tmp_path)
    first_content = {path.name: path.read_bytes() for path in first}
    second = exporter.export(warehouse_delta_report, tmp_path)
    assert first_content == {path.name: path.read_bytes() for path in second}
    assert len(first) == 9
    required = {
        "price_delta.csv",
        "indicator_delta.csv",
        "candidate_delta.csv",
        "decision_delta.csv",
        "replay_delta.csv",
        "corporate_action_delta.csv",
        "purchase_justification.md",
        "executive_report.md",
        "manifest.json",
    }
    assert {path.name for path in first} == required
    personal = (tmp_path / "purchase_justification.md").read_text()
    assert (
        "Would I personally spend ₹315,000 of my own money after seeing these results?"
        in personal
    )
    assert "## Not yet" in personal
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["production_influence"] is False
    assert manifest["no_replay_changes"] is True


def test_cli_replay_and_report_render_persisted_evidence(
    tmp_path: Path,
    warehouse_delta_report: WarehouseDeltaReport,
) -> None:
    WarehouseDeltaExporter().export(warehouse_delta_report, tmp_path)
    runner = CliRunner()
    replay = runner.invoke(
        warehouse_delta_app,
        ["replay", "--output", str(tmp_path)],
    )
    report = runner.invoke(
        warehouse_delta_app,
        ["report", "--output", str(tmp_path)],
    )
    assert replay.exit_code == report.exit_code == 0
    assert "Identical settings: YES" in replay.stdout
    assert "expectancy" in replay.stdout
    assert "Warehouse Delta Audit v1.0" in report.stdout
    assert "PRODUCTION_INFLUENCE=false" in report.stdout


def test_cli_audit_exports_the_complete_report(
    tmp_path: Path,
    warehouse_delta_report: WarehouseDeltaReport,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        WarehouseDeltaAuditEngine,
        "run",
        lambda self, request, project_root, progress=None: warehouse_delta_report,
    )
    output = tmp_path / "output"
    result = CliRunner().invoke(
        warehouse_delta_app,
        [
            "audit",
            "--database",
            str(tmp_path / "legacy.duckdb"),
            "--comparison-source",
            str(tmp_path / "source"),
            "--output",
            str(output),
            "--sample-size",
            "7",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert "COMPLETE_SAME_LINEAGE_CONTROL" in result.stdout
    assert "Personal Decision: Not yet" in result.stdout
    assert (output / "executive_report.md").exists()
    assert (output / "purchase_justification.md").exists()


def test_rendered_personal_answer_is_one_of_the_allowed_values(
    warehouse_delta_report: WarehouseDeltaReport,
) -> None:
    rendered = render_purchase_justification(warehouse_delta_report)
    assert "## Not yet" in rendered
    assert "## Yes" not in rendered
    assert "## No\n" not in rendered
