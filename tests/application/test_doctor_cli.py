from typer.testing import CliRunner

from alpha.cli import app

runner = CliRunner()


def test_doctor_command_prints_release_metadata() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Name: Project Alpha" in result.stdout
    assert "Version: 1.2.0" in result.stdout
    assert "Stage: v1.2" in result.stdout
    assert "Status: engineering" in result.stdout
    assert "- deterministic backtesting" in result.stdout
    assert "- financial accounting model" in result.stdout
    assert "- explainable JSON exports" in result.stdout
    assert "- poetry build" in result.stdout
