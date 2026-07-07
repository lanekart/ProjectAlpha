"""Application services and Typer app for the research CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

import typer

from alpha.research import (
    MarkdownResearchReportFormatter,
    ResearchExperimentManifest,
    ResearchExperimentRecord,
    ResearchReport,
    ResearchReportBuilder,
    ResearchSession,
    ResearchSessionEntry,
    StrategyComparisonEngine,
    StrategyComparisonReport,
    TextResearchReportFormatter,
)

ResearchOutputFormat = Literal["text", "markdown"]

research_app = typer.Typer(help="Research workflow commands.")


@dataclass(frozen=True, slots=True)
class ResearchCLIService:
    """Application service backing deterministic research CLI commands."""

    def status(self) -> str:
        """Return a deterministic research subsystem status summary."""

        lines = (
            "Project Alpha Research",
            "Status: ready",
            "Capabilities:",
            "- walk-forward validation",
            "- parameter sweeps",
            "- experiment persistence",
            "- research sessions",
            "- strategy comparison",
            "- professional reports",
        )
        return "\n".join(lines) + "\n"

    def demo_session(self) -> str:
        """Return a deterministic demo research session summary."""

        session = build_demo_research_session()
        lines = (
            "Research Session",
            f"Session ID: {session.session_id}",
            f"Name: {session.name}",
            f"Entries: {session.entry_count}",
            f"Objective metrics: {', '.join(session.objective_metrics)}",
            f"Best strategy: {session.best_entry.strategy_name}",
            f"Best label: {session.best_entry.label}",
            f"Best value: {session.best_entry.best_objective_value}",
        )
        return "\n".join(lines) + "\n"

    def demo_comparison(self) -> str:
        """Return a deterministic demo strategy comparison summary."""

        report = build_demo_strategy_comparison()
        lines = [
            "Strategy Comparison",
            f"Session ID: {report.session_id}",
            f"Objective metric: {report.objective_metric}",
            f"Results: {report.result_count}",
            f"Strategies: {report.strategy_count}",
        ]
        lines.extend(
            "Rank "
            f"{result.comparison_rank}: "
            f"{result.strategy_name} / {result.label} "
            f"= {result.objective_value}"
            for result in report.results
        )
        return "\n".join(lines) + "\n"

    def demo_report(self, output_format: ResearchOutputFormat = "text") -> str:
        """Return a deterministic formatted professional research report."""

        session = build_demo_research_session()
        comparison_report = build_demo_strategy_comparison()
        report = ResearchReportBuilder().build_session_report(
            session=session,
            comparison_report=comparison_report,
            title="Project Alpha Research Demo",
        )
        return format_research_report(report=report, output_format=output_format)


@research_app.command("status")
def research_status() -> None:
    """Show research subsystem status."""

    typer.echo(ResearchCLIService().status(), nl=False)


@research_app.command("session")
def research_session() -> None:
    """Show a deterministic demo research session."""

    typer.echo(ResearchCLIService().demo_session(), nl=False)


@research_app.command("compare")
def research_compare() -> None:
    """Show a deterministic demo strategy comparison."""

    typer.echo(ResearchCLIService().demo_comparison(), nl=False)


@research_app.command("report")
def research_report(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: text or markdown.",
        ),
    ] = "text",
) -> None:
    """Render a deterministic demo professional research report."""

    parsed_format = _parse_research_output_format(output_format)
    typer.echo(ResearchCLIService().demo_report(parsed_format), nl=False)


def build_demo_research_session() -> ResearchSession:
    """Build a deterministic in-memory demo session for CLI smoke workflows."""

    entries = (
        ResearchSessionEntry(
            label="baseline",
            strategy_name="momentum",
            manifest=_manifest(
                run_id="demo-baseline",
                objective_value=Decimal("1.10"),
                lookback=20,
                threshold=Decimal("0.05"),
            ),
        ),
        ResearchSessionEntry(
            label="candidate",
            strategy_name="mean_reversion",
            manifest=_manifest(
                run_id="demo-candidate",
                objective_value=Decimal("1.25"),
                lookback=10,
                threshold=Decimal("0.03"),
            ),
        ),
    )
    return ResearchSession(
        session_id="demo-session",
        name="Research CLI Demo Session",
        entries=entries,
        description="Deterministic in-memory research session for CLI validation.",
        metadata={"environment": "demo"},
    )


def build_demo_strategy_comparison() -> StrategyComparisonReport:
    """Build a deterministic comparison report for the demo session."""

    return StrategyComparisonEngine(objective_metric="score").compare(
        session=build_demo_research_session(),
        metadata={"source": "research_cli"},
    )


def format_research_report(
    *,
    report: ResearchReport,
    output_format: ResearchOutputFormat,
) -> str:
    """Format a professional research report for CLI output."""

    if output_format == "text":
        return TextResearchReportFormatter().format(report)
    if output_format == "markdown":
        return MarkdownResearchReportFormatter().format(report)
    raise ValueError(f"unsupported research output format: {output_format}")


def supported_output_formats() -> Mapping[str, ResearchOutputFormat]:
    """Return supported output formats keyed by CLI option value."""

    return {
        "text": "text",
        "markdown": "markdown",
    }


def _parse_research_output_format(output_format: str) -> ResearchOutputFormat:
    normalized_format = output_format.strip().lower()
    formats = supported_output_formats()
    if normalized_format not in formats:
        raise typer.BadParameter("Research report format must be text or markdown.")
    return formats[normalized_format]


def _manifest(
    *,
    run_id: str,
    objective_value: Decimal,
    lookback: int,
    threshold: Decimal,
) -> ResearchExperimentManifest:
    record = ResearchExperimentRecord(
        experiment_id=f"{run_id}-best",
        parameters={"lookback": lookback, "threshold": threshold},
        objective_metric="score",
        objective_value=objective_value,
        rank=1,
    )
    return ResearchExperimentManifest(
        run_id=run_id,
        objective_metric="score",
        records=(record,),
    )


__all__ = [
    "ResearchCLIService",
    "ResearchOutputFormat",
    "build_demo_research_session",
    "build_demo_strategy_comparison",
    "format_research_report",
    "research_app",
    "supported_output_formats",
]
