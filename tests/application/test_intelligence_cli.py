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


def test_intelligence_command_is_visible_in_root_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "intelligence" in result.stdout
