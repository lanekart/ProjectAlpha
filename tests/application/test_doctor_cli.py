from typer.testing import CliRunner

from alpha.cli import app

runner = CliRunner()


def test_doctor_command_prints_release_metadata() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Name: Project Alpha" in result.stdout
    assert "Version: 1.3.0-dev" in result.stdout
    assert "Stage: v1.3-production-validation" in result.stdout
    assert "Status: production validation" in result.stdout
    assert "- deterministic backtesting" in result.stdout
    assert "- financial accounting model" in result.stdout
    assert "- explainable JSON exports" in result.stdout
    assert "- recommendation intelligence" in result.stdout
    assert "- portfolio intelligence" in result.stdout
    assert "- runtime validation" in result.stdout
    assert "- user acceptance testing" in result.stdout
