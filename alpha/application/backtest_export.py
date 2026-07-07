from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from alpha.application.backtest import BacktestSummary
from alpha.backtest.backtest_export_manifest import (
    BacktestExportArtifact,
    BacktestExportManifest,
)
from alpha.backtest.backtest_export_session import BacktestExportSession
from alpha.backtest.backtest_report_artifact_naming import BacktestReportArtifactNamer
from alpha.backtest.backtest_report_writer import BacktestReportWriter


@dataclass(frozen=True, slots=True)
class BacktestExportResult:
    """Immutable result describing persisted backtest report outputs."""

    json_path: Path | None = None
    text_path: Path | None = None
    session: BacktestExportSession | None = None
    manifest: BacktestExportManifest = field(
        default_factory=lambda: BacktestExportManifest(())
    )

    def __post_init__(self) -> None:
        artifacts: list[BacktestExportArtifact] = []

        if self.json_path is not None:
            artifacts.append(BacktestExportArtifact(kind="json", path=self.json_path))

        if self.text_path is not None:
            artifacts.append(BacktestExportArtifact(kind="text", path=self.text_path))

        manifest = BacktestExportManifest(artifacts, session=self.session)
        object.__setattr__(self, "manifest", manifest)

    @property
    def wrote_any(self) -> bool:
        return not self.manifest.is_empty


@dataclass(frozen=True, slots=True)
class BacktestExportService:
    """Application service for persisting completed backtest summaries."""

    writer: BacktestReportWriter = BacktestReportWriter()
    namer: BacktestReportArtifactNamer = BacktestReportArtifactNamer()

    def export(
        self,
        summary: BacktestSummary,
        *,
        json_path: Path | None = None,
        text_path: Path | None = None,
    ) -> BacktestExportResult:
        session = self._session_from_summary(summary)
        written_json_path: Path | None = None
        written_text_path: Path | None = None

        if json_path is not None:
            written_json_path = self.writer.write_json(summary.report, json_path)

        if text_path is not None:
            written_text_path = self.writer.write_text(summary.report, text_path)

        return BacktestExportResult(
            json_path=written_json_path,
            text_path=written_text_path,
            session=session,
        )

    def export_to_directory(
        self,
        summary: BacktestSummary,
        *,
        directory: Path,
        include_json: bool = True,
        include_text: bool = True,
    ) -> BacktestExportResult:
        if not include_json and not include_text:
            return BacktestExportResult(session=self._session_from_summary(summary))

        json_path: Path | None = None
        text_path: Path | None = None

        if include_json:
            json_name = self.namer.name(
                strategy=summary.strategy,
                start=summary.start,
                end=summary.end,
                suffix=".json",
            )
            json_path = directory / json_name.value

        if include_text:
            text_name = self.namer.name(
                strategy=summary.strategy,
                start=summary.start,
                end=summary.end,
                suffix=".txt",
            )
            text_path = directory / text_name.value

        return self.export(
            summary,
            json_path=json_path,
            text_path=text_path,
        )

    def _session_from_summary(self, summary: BacktestSummary) -> BacktestExportSession:
        return BacktestExportSession(
            strategy=summary.strategy,
            start=summary.start.isoformat(),
            end=summary.end.isoformat(),
        )
