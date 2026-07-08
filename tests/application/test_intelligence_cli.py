from __future__ import annotations

import json

from typer.testing import CliRunner

from alpha.cli import app

runner = CliRunner()


def test_intelligence_command_prints_orchestrated_report() -> None:
    result = runner.invoke(app, ["intelligence", "--date", "2026-01-30"])

    assert result.exit_code == 0
    assert "Project Alpha Intelligence Report" in result.stdout
    assert "Observed On      : 2026-01-30" in result.stdout
    assert "Market Bias      :" in result.stdout
    assert "Composite Score  :" in result.stdout
    assert "Market Intelligence Reasons:" in result.stdout
    assert "Recommendations:" in result.stdout
    assert "HAL:" in result.stdout
    assert "Portfolio Allocation:" in result.stdout
    assert "Allocated Weight :" in result.stdout
    assert "Remaining Cash   :" in result.stdout


def test_intelligence_command_exports_json_and_text(tmp_path) -> None:
    json_path = tmp_path / "recommendations.json"
    text_path = tmp_path / "recommendations.txt"

    result = runner.invoke(
        app,
        [
            "intelligence",
            "--date",
            "2026-01-30",
            "--export-json",
            str(json_path),
            "--export-text",
            str(text_path),
        ],
    )

    assert result.exit_code == 0
    assert "JSON report written:" in result.stdout
    assert "Text report written:" in result.stdout
    assert json_path.exists()
    assert text_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "recommendation_report"
    assert payload["observed_on"] == "2026-01-30"
    assert [item["symbol"] for item in payload["recommendations"]] == [
        "HAL",
        "LT",
        "BEL",
    ]


def test_intelligence_command_rejects_invalid_export_suffix(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "intelligence",
            "--date",
            "2026-01-30",
            "--export-json",
            str(tmp_path / "recommendations.txt"),
        ],
    )

    assert result.exit_code != 0
    assert "Expected --export-json path to end with .json." in result.stdout


def test_intelligence_command_rejects_invalid_text_export_suffix(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "intelligence",
            "--date",
            "2026-01-30",
            "--export-text",
            str(tmp_path / "recommendations.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Expected --export-text path to end with .txt." in result.stdout


def test_intelligence_command_is_visible_in_root_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "intelligence" in result.stdout
