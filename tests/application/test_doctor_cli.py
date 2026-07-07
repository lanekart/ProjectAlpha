from typer.testing import CliRunner

from alpha.cli import app

runner = CliRunner()


def test_doctor_command_prints_release_metadata() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Name: Project Alpha" in result.stdout
    assert "Version: 1.0.0" in result.stdout
    assert "Stage: v1.0" in result.stdout
    assert "Status: release candidate" in result.stdout
    assert "- deterministic backtesting" in result.stdout
    assert "- research CLI" in result.stdout
    assert "- pytest" in result.stdout
    assert "- ruff" in result.stdout
    assert "- mypy" in result.stdout
