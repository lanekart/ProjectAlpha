from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.pine_cli import pine_app

runner = CliRunner()


def test_audit_command() -> None:
    result = runner.invoke(pine_app, ["audit"])

    assert result.exit_code == 0
    assert "Alpha Pine Parity Audit" in result.stdout
    assert "UNAVAILABLE_IN_TRADINGVIEW" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_manifest_command_exports_json(tmp_path: Path) -> None:
    result = runner.invoke(pine_app, ["manifest", "--output", str(tmp_path)])

    assert result.exit_code == 0
    framework = json.loads(
        (tmp_path / "alpha_framework_manifest.json").read_text(encoding="utf-8")
    )
    assert framework["components"]["price_structure"] == "0.20"


def test_export_command_applies_overrides(tmp_path: Path) -> None:
    output = tmp_path / "export.pine"
    result = runner.invoke(
        pine_app,
        [
            "export",
            "--strategy",
            "risk-exit-lab",
            "--stop-model",
            "SWING_LOW",
            "--target-model",
            "3R",
            "--entry-threshold",
            "80",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    source = output.read_text(encoding="utf-8")
    assert "// ALPHA_DEFAULT_STOP_MODEL=SWING_LOW" in source
    assert 'input.string("SWING_LOW", "Stop model"' in source
    assert 'input.string("3R", "Target model"' in source
    assert "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED" in result.stdout


def test_export_command_accepts_config_file(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "timeframe": "240",
                "confirmation_timeframe": "60",
                "entry_threshold": "81",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "mtf.pine"

    result = runner.invoke(
        pine_app,
        [
            "export",
            "--strategy",
            "multi-timeframe-composite",
            "--config",
            str(config),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    source = output.read_text(encoding="utf-8")
    assert 'input.timeframe("240", "Primary setup timeframe"' in source
    assert 'input.timeframe("60", "Confirmation timeframe"' in source


def test_validate_and_report_commands() -> None:
    validation = runner.invoke(pine_app, ["validate"])
    report = runner.invoke(pine_app, ["report"])

    assert validation.exit_code == 0
    assert "PINE_STATIC_VALIDATION=PASS" in validation.stdout
    assert report.exit_code == 0
    assert "ALPHA_SOURCE_OF_TRUTH=true" in report.stdout
    assert "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED" in report.stdout


def test_validate_file_writes_machine_readable_report(tmp_path: Path) -> None:
    report_path = tmp_path / "validation.json"
    source = Path("tradingview/generated/Alpha_03_Institutional_Composite.pine")

    result = runner.invoke(
        pine_app,
        [
            "validate",
            "--file",
            str(source),
            "--strict",
            "--json-output",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["strict"] is True
    assert payload["files"][0]["status"] == "PASS"
    assert payload["files"][0]["errors"] == []
    assert payload["files"][0]["warnings"] == []


def test_compilation_checklist_keeps_verification_statuses_separate() -> None:
    result = runner.invoke(pine_app, ["compilation-checklist"])

    assert result.exit_code == 0
    assert "PYTHON_GENERATION_TESTS=NOT_RUN" in result.stdout
    assert "PINE_STATIC_VALIDATION=NOT_RUN" in result.stdout
    assert "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED" in result.stdout
    assert "TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED" in result.stdout


def test_export_rejects_configuration_injection(tmp_path: Path) -> None:
    output = tmp_path / "bad.pine"
    result = runner.invoke(
        pine_app,
        [
            "export",
            "--strategy",
            "institutional-composite",
            "--timeframe",
            'D")\nplot(close)',
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert not output.exists()
