from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alpha.backtest.backtest_report import BacktestReport, BacktestReportRenderer


@dataclass(frozen=True, slots=True)
class BacktestReportWriter:
    """Persist unified backtest reports in deterministic file formats."""

    renderer: BacktestReportRenderer = BacktestReportRenderer()

    def write_json(
        self,
        report: BacktestReport,
        path: Path,
        *,
        indent: int | None = 2,
    ) -> Path:
        self._ensure_supported_path(path=path, expected_suffix=".json")
        self._ensure_parent_directory(path)
        path.write_text(report.as_json(indent=indent), encoding="utf-8")
        return path

    def write_text(self, report: BacktestReport, path: Path) -> Path:
        self._ensure_supported_path(path=path, expected_suffix=".txt")
        self._ensure_parent_directory(path)
        content = "\n".join(self.renderer.render(report))
        path.write_text(f"{content}\n", encoding="utf-8")
        return path

    def _ensure_supported_path(self, *, path: Path, expected_suffix: str) -> None:
        if path.suffix.lower() != expected_suffix:
            raise ValueError(f"expected {expected_suffix} output path")

    def _ensure_parent_directory(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
