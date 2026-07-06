from decimal import Decimal

import pytest

from alpha.research import (
    MarkdownResearchReportFormatter,
    ResearchExperimentManifest,
    ResearchExperimentRecord,
    ResearchReport,
    ResearchReportBuilder,
    ResearchReportSection,
    ResearchSession,
    ResearchSessionEntry,
    StrategyComparisonEngine,
    TextResearchReportFormatter,
)


def make_manifest(
    *,
    run_id: str,
    objective_value: Decimal,
    parameter_value: int,
) -> ResearchExperimentManifest:
    return ResearchExperimentManifest(
        run_id=run_id,
        objective_metric="score",
        records=(
            ResearchExperimentRecord(
                experiment_id=f"{run_id}-best",
                parameters={"lookback": parameter_value},
                objective_metric="score",
                objective_value=objective_value,
                rank=1,
            ),
        ),
    )


def make_session() -> ResearchSession:
    return ResearchSession(
        session_id="session-1",
        name="Momentum Research Report",
        description="Compare momentum variants.",
        metadata={"owner": "research"},
        entries=(
            ResearchSessionEntry(
                label="baseline",
                strategy_name="momentum",
                manifest=make_manifest(
                    run_id="run-1",
                    objective_value=Decimal("1.10"),
                    parameter_value=20,
                ),
            ),
            ResearchSessionEntry(
                label="candidate",
                strategy_name="breakout",
                manifest=make_manifest(
                    run_id="run-2",
                    objective_value=Decimal("1.40"),
                    parameter_value=55,
                ),
            ),
        ),
    )


def test_research_report_builder_builds_session_report() -> None:
    report = ResearchReportBuilder().build_session_report(session=make_session())

    assert report.title == "Momentum Research Report"
    assert report.section_count == 4
    assert report.section_titles == (
        "Executive Summary",
        "Best Result",
        "Session Entries",
        "Session Metadata",
    )
    assert report.section("Best Result").lines == (
        "Strategy: breakout",
        "Label: candidate",
        "Run ID: run-2",
        "Objective metric: score",
        "Objective value: 1.40",
        "Best parameters: lookback=55",
    )


def test_research_report_builder_includes_strategy_comparison() -> None:
    session = make_session()
    comparison = StrategyComparisonEngine(objective_metric="score").compare(
        session=session
    )

    report = ResearchReportBuilder().build_session_report(
        session=session,
        comparison_report=comparison,
        title="Custom Report",
        metadata={"version": 1},
    )

    assert report.title == "Custom Report"
    assert report.metadata == {"version": 1}
    assert report.section_titles == (
        "Executive Summary",
        "Best Result",
        "Strategy Comparison",
        "Session Entries",
        "Session Metadata",
    )
    assert report.section("Strategy Comparison").lines == (
        "Rank 1: breakout / candidate = 1.40",
        "Rank 2: momentum / baseline = 1.10",
    )


def test_markdown_research_report_formatter_is_deterministic() -> None:
    report = ResearchReportBuilder().build_session_report(session=make_session())

    rendered = MarkdownResearchReportFormatter().format(report)

    assert rendered.startswith("# Momentum Research Report\n\n")
    assert "## Executive Summary" in rendered
    assert "- Entries evaluated: 2" in rendered
    assert "## Best Result" in rendered
    assert rendered.endswith("- owner: research\n")


def test_text_research_report_formatter_is_deterministic() -> None:
    report = ResearchReportBuilder().build_session_report(session=make_session())

    rendered = TextResearchReportFormatter().format(report)

    assert rendered.startswith("Momentum Research Report\n========================\n\n")
    assert "Executive Summary\n-----------------" in rendered
    assert "* Objective value: 1.40" in rendered
    assert rendered.endswith("* owner: research\n")


def test_research_report_value_objects_validate_inputs() -> None:
    with pytest.raises(ValueError, match="title"):
        ResearchReportSection(title=" ", lines=("line",))

    with pytest.raises(ValueError, match="line"):
        ResearchReportSection(title="Summary", lines=(" ",))

    section = ResearchReportSection(title="Summary", lines=("line",))

    with pytest.raises(ValueError, match="duplicate sections"):
        ResearchReport(title="Report", sections=(section, section))


def test_research_report_section_lookup_validates_title() -> None:
    report = ResearchReport(
        title="Report",
        sections=(ResearchReportSection(title="Summary", lines=("line",)),),
    )

    with pytest.raises(ValueError, match="section title"):
        report.section(" ")

    with pytest.raises(KeyError, match="unknown research report section"):
        report.section("Missing")


def test_research_report_rejects_mismatched_comparison_report() -> None:
    session = make_session()
    other_session = ResearchSession(
        session_id="session-2",
        name=session.name,
        entries=session.entries,
    )
    comparison = StrategyComparisonEngine(objective_metric="score").compare(
        session=other_session
    )

    with pytest.raises(ValueError, match="session_id"):
        ResearchReportBuilder().build_session_report(
            session=session,
            comparison_report=comparison,
        )
