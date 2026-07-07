from typer.testing import CliRunner

from alpha.application.research_cli import (
    ResearchCLIService,
    build_demo_research_session,
    build_demo_strategy_comparison,
)
from alpha.cli import app

runner = CliRunner()


def test_research_cli_service_reports_status() -> None:
    output = ResearchCLIService().status()

    assert "Project Alpha Research" in output
    assert "Status: ready" in output
    assert "professional reports" in output


def test_research_cli_demo_session_is_deterministic() -> None:
    output = ResearchCLIService().demo_session()

    assert "Session ID: demo-session" in output
    assert "Best strategy: mean_reversion" in output
    assert "Best value: 1.25" in output


def test_research_cli_demo_comparison_is_ranked() -> None:
    output = ResearchCLIService().demo_comparison()

    assert "Strategy Comparison" in output
    assert "Rank 1: mean_reversion / candidate = 1.25" in output
    assert "Rank 2: momentum / baseline = 1.10" in output


def test_research_cli_demo_report_supports_text_format() -> None:
    output = ResearchCLIService().demo_report("text")

    assert output.startswith("Project Alpha Research Demo")
    assert "Executive Summary" in output
    assert "* Session ID: demo-session" in output


def test_research_cli_demo_report_supports_markdown_format() -> None:
    output = ResearchCLIService().demo_report("markdown")

    assert output.startswith("# Project Alpha Research Demo")
    assert "## Strategy Comparison" in output
    assert "- Rank 1: mean_reversion / candidate = 1.25" in output


def test_demo_research_session_has_expected_shape() -> None:
    session = build_demo_research_session()

    assert session.session_id == "demo-session"
    assert session.entry_count == 2
    assert session.best_entry.label == "candidate"


def test_demo_strategy_comparison_has_expected_shape() -> None:
    report = build_demo_strategy_comparison()

    assert report.session_id == "demo-session"
    assert report.result_count == 2
    assert report.best_result.strategy_name == "mean_reversion"


def test_research_status_command() -> None:
    result = runner.invoke(app, ["research", "status"])

    assert result.exit_code == 0
    assert "Project Alpha Research" in result.stdout
    assert "Status: ready" in result.stdout


def test_research_session_command() -> None:
    result = runner.invoke(app, ["research", "session"])

    assert result.exit_code == 0
    assert "Research Session" in result.stdout
    assert "Best label: candidate" in result.stdout


def test_research_compare_command() -> None:
    result = runner.invoke(app, ["research", "compare"])

    assert result.exit_code == 0
    assert "Strategy Comparison" in result.stdout
    assert "Rank 1: mean_reversion / candidate = 1.25" in result.stdout


def test_research_report_command_defaults_to_text() -> None:
    result = runner.invoke(app, ["research", "report"])

    assert result.exit_code == 0
    assert result.stdout.startswith("Project Alpha Research Demo")
    assert "* Session ID: demo-session" in result.stdout


def test_research_report_command_supports_markdown() -> None:
    result = runner.invoke(app, ["research", "report", "--format", "markdown"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# Project Alpha Research Demo")
    assert "- Session ID: demo-session" in result.stdout


def test_research_report_command_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["research", "report", "--format", "json"])

    assert result.exit_code != 0
    assert "Research report format must be text or markdown." in result.stderr
