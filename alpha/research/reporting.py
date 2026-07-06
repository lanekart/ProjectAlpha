"""Deterministic professional research reporting primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol

from alpha.research.comparison import StrategyComparisonReport
from alpha.research.session import ResearchSession, ResearchSessionEntry

ReportMetadataValue = bool | int | str | Decimal


@dataclass(frozen=True, slots=True)
class ResearchReportSection:
    """Immutable section in a professional research report."""

    title: str
    lines: tuple[str, ...]
    metadata: Mapping[str, ReportMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_title = self.title.strip()
        if not normalized_title:
            raise ValueError("report section title cannot be empty")
        if len(self.lines) == 0:
            raise ValueError("report section requires at least one line")

        normalized_lines: list[str] = []
        for line in self.lines:
            normalized_line = line.strip()
            if not normalized_line:
                raise ValueError("report section line cannot be empty")
            normalized_lines.append(normalized_line)

        copied_metadata: dict[str, ReportMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("report section metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "lines", tuple(normalized_lines))
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))


@dataclass(frozen=True, slots=True)
class ResearchReport:
    """Immutable professional research report."""

    title: str
    sections: tuple[ResearchReportSection, ...]
    metadata: Mapping[str, ReportMetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_title = self.title.strip()
        if not normalized_title:
            raise ValueError("research report title cannot be empty")
        if len(self.sections) == 0:
            raise ValueError("research report requires at least one section")

        titles = tuple(section.title for section in self.sections)
        if len(set(titles)) != len(titles):
            raise ValueError("research report cannot contain duplicate sections")

        copied_metadata: dict[str, ReportMetadataValue] = {}
        for name, value in self.metadata.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("research report metadata name cannot be empty")
            copied_metadata[normalized_name] = value

        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))

    @property
    def section_count(self) -> int:
        """Return number of report sections."""

        return len(self.sections)

    @property
    def section_titles(self) -> tuple[str, ...]:
        """Return report section titles in deterministic order."""

        return tuple(section.title for section in self.sections)

    def section(self, title: str) -> ResearchReportSection:
        """Return a section by title."""

        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("section title cannot be empty")

        for section in self.sections:
            if section.title == normalized_title:
                return section

        raise KeyError(f"unknown research report section: {normalized_title}")


class ResearchReportFormatter(Protocol):
    """Protocol for deterministic research report formatters."""

    def format(self, report: ResearchReport) -> str:
        """Format a research report."""

        ...


@dataclass(frozen=True, slots=True)
class MarkdownResearchReportFormatter:
    """Render research reports as deterministic Markdown."""

    def format(self, report: ResearchReport) -> str:
        """Format a research report as Markdown."""

        lines = [f"# {report.title}", ""]
        for section in report.sections:
            lines.append(f"## {section.title}")
            lines.extend(f"- {line}" for line in section.lines)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class TextResearchReportFormatter:
    """Render research reports as deterministic plain text."""

    def format(self, report: ResearchReport) -> str:
        """Format a research report as plain text."""

        lines = [report.title, "=" * len(report.title), ""]
        for section in report.sections:
            lines.append(section.title)
            lines.append("-" * len(section.title))
            lines.extend(f"* {line}" for line in section.lines)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class ResearchReportBuilder:
    """Build professional research reports from research aggregates."""

    def build_session_report(
        self,
        *,
        session: ResearchSession,
        comparison_report: StrategyComparisonReport | None = None,
        title: str | None = None,
        metadata: Mapping[str, ReportMetadataValue] | None = None,
    ) -> ResearchReport:
        """Build a deterministic professional report for a research session."""

        report_title = session.name if title is None else title
        sections = [
            _executive_summary_section(session=session),
            _best_result_section(session=session),
            _session_entries_section(session=session),
        ]

        if comparison_report is not None:
            _validate_comparison_report(
                session=session,
                comparison_report=comparison_report,
            )
            sections.insert(
                2,
                _strategy_comparison_section(comparison_report=comparison_report),
            )

        if len(session.metadata) > 0:
            sections.append(_metadata_section(metadata=session.metadata))

        return ResearchReport(
            title=report_title,
            sections=tuple(sections),
            metadata={} if metadata is None else metadata,
        )


def _executive_summary_section(
    *,
    session: ResearchSession,
) -> ResearchReportSection:
    metrics = ", ".join(session.objective_metrics)
    return ResearchReportSection(
        title="Executive Summary",
        lines=(
            f"Session ID: {session.session_id}",
            f"Research session: {session.name}",
            f"Entries evaluated: {session.entry_count}",
            f"Objective metrics: {metrics}",
        ),
    )


def _best_result_section(
    *,
    session: ResearchSession,
) -> ResearchReportSection:
    entry = session.best_entry
    record = entry.best_record
    parameters = _format_mapping(record.parameters)
    return ResearchReportSection(
        title="Best Result",
        lines=(
            f"Strategy: {entry.strategy_name}",
            f"Label: {entry.label}",
            f"Run ID: {entry.run_id}",
            f"Objective metric: {entry.objective_metric}",
            f"Objective value: {entry.best_objective_value}",
            f"Best parameters: {parameters}",
        ),
    )


def _strategy_comparison_section(
    *,
    comparison_report: StrategyComparisonReport,
) -> ResearchReportSection:
    lines = tuple(
        "Rank "
        f"{result.comparison_rank}: "
        f"{result.strategy_name} / {result.label} "
        f"= {result.objective_value}"
        for result in comparison_report.results
    )
    return ResearchReportSection(
        title="Strategy Comparison",
        lines=lines,
    )


def _session_entries_section(
    *,
    session: ResearchSession,
) -> ResearchReportSection:
    lines = tuple(_format_entry(entry) for entry in session.entries)
    return ResearchReportSection(title="Session Entries", lines=lines)


def _metadata_section(
    *,
    metadata: Mapping[str, ReportMetadataValue],
) -> ResearchReportSection:
    return ResearchReportSection(
        title="Session Metadata",
        lines=tuple(f"{name}: {value}" for name, value in sorted(metadata.items())),
    )


def _format_entry(entry: ResearchSessionEntry) -> str:
    return (
        f"{entry.label}: {entry.strategy_name}, "
        f"run={entry.run_id}, "
        f"{entry.objective_metric}={entry.best_objective_value}"
    )


def _format_mapping(metadata: Mapping[str, object]) -> str:
    if len(metadata) == 0:
        return "none"
    return ", ".join(f"{name}={value}" for name, value in sorted(metadata.items()))


def _validate_comparison_report(
    *,
    session: ResearchSession,
    comparison_report: StrategyComparisonReport,
) -> None:
    if comparison_report.session_id != session.session_id:
        raise ValueError("comparison report session_id does not match session")
