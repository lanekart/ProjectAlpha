from __future__ import annotations

from typer.testing import CliRunner

from alpha.cli import app
from alpha.exceptions import BhavcopyNotFoundError

runner = CliRunner()


def test_download_command_reports_data_error(monkeypatch) -> None:
    def raise_error(self, date: str) -> int:
        raise BhavcopyNotFoundError("No NSE bhavcopy found")

    monkeypatch.setattr(
        "alpha.application.historical_ingestion."
        "HistoricalIngestionService.download_only",
        raise_error,
    )

    result = runner.invoke(app, ["download"])

    assert result.exit_code == 1
    assert "Data download failed" in result.stderr
    assert "No NSE bhavcopy found" in result.stderr


def test_report_command_reports_data_error(monkeypatch) -> None:
    def raise_error(self, date: str) -> dict[str, object]:
        raise BhavcopyNotFoundError("No NSE bhavcopy found")

    monkeypatch.setattr(
        "alpha.application.historical_ingestion."
        "HistoricalIngestionService.generate_report",
        raise_error,
    )

    result = runner.invoke(app, ["report"])

    assert result.exit_code == 1
    assert "Report generation failed" in result.stderr
    assert "No NSE bhavcopy found" in result.stderr
