from __future__ import annotations

from datetime import date

import pytest

from alpha.backtest import BacktestReportArtifactName, BacktestReportArtifactNamer


def test_backtest_report_artifact_namer_builds_json_name() -> None:
    name = BacktestReportArtifactNamer().name(
        strategy="Momentum",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        suffix=".json",
    )

    assert name.value == "backtest_momentum_2024-01-01_2024-01-31.json"


def test_backtest_report_artifact_namer_builds_text_name() -> None:
    name = BacktestReportArtifactNamer(prefix="Project Alpha").name(
        strategy="High Momentum / NSE",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        suffix=".TXT",
    )

    assert name.value == ("project_alpha_high_momentum_nse_2024-01-01_2024-01-31.txt")


def test_backtest_report_artifact_namer_rejects_empty_prefix() -> None:
    with pytest.raises(ValueError, match="prefix cannot be empty"):
        BacktestReportArtifactNamer(prefix=" !!! ")


def test_backtest_report_artifact_namer_rejects_empty_strategy() -> None:
    with pytest.raises(ValueError, match="strategy cannot be empty"):
        BacktestReportArtifactNamer().name(
            strategy=" !!! ",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            suffix=".json",
        )


def test_backtest_report_artifact_namer_rejects_invalid_date_range() -> None:
    with pytest.raises(ValueError, match="end date must be on or after start date"):
        BacktestReportArtifactNamer().name(
            strategy="momentum",
            start=date(2024, 1, 31),
            end=date(2024, 1, 1),
            suffix=".json",
        )


def test_backtest_report_artifact_namer_rejects_unsupported_suffix() -> None:
    with pytest.raises(ValueError, match="unsupported artifact suffix"):
        BacktestReportArtifactNamer().name(
            strategy="momentum",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            suffix=".csv",
        )


def test_backtest_report_artifact_name_rejects_path_separators() -> None:
    with pytest.raises(ValueError, match="artifact name cannot contain path"):
        BacktestReportArtifactName("nested/report.json")
