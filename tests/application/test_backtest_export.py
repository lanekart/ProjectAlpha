from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.application.backtest import BacktestSummary
from alpha.application.backtest_export import BacktestExportService
from alpha.backtest.models import BacktestResult


def make_summary() -> BacktestSummary:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("100"),
        equity=Decimal("1100"),
        positions={"AAPL": 10},
        trades=(),
    )
    return BacktestSummary(
        strategy="momentum",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        equity=result.equity,
        processed_days=22,
        order_count=1,
        trade_count=0,
        position_count=1,
        positions=result.positions,
        result=result,
    )


def test_backtest_export_service_returns_empty_result_when_no_paths() -> None:
    result = BacktestExportService().export(make_summary())

    assert result.wrote_any is False
    assert result.json_path is None
    assert result.text_path is None
    assert result.session is not None
    assert result.session.strategy == "momentum"
    assert result.manifest.is_empty is True
    assert "session" in result.manifest.as_dict()


def test_backtest_export_service_writes_json(tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"

    result = BacktestExportService().export(
        make_summary(),
        json_path=output_path,
    )

    assert result.wrote_any is True
    assert result.json_path == output_path
    assert result.text_path is None
    assert result.manifest.artifact_count == 1
    assert "session" in result.manifest.as_dict()
    assert output_path.exists()


def test_backtest_export_service_writes_text(tmp_path: Path) -> None:
    output_path = tmp_path / "report.txt"

    result = BacktestExportService().export(
        make_summary(),
        text_path=output_path,
    )

    assert result.wrote_any is True
    assert result.json_path is None
    assert result.text_path == output_path
    assert result.manifest.artifact_count == 1
    assert "session" in result.manifest.as_dict()
    assert output_path.exists()


def test_backtest_export_service_writes_json_and_text(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    text_path = tmp_path / "report.txt"

    result = BacktestExportService().export(
        make_summary(),
        json_path=json_path,
        text_path=text_path,
    )

    assert result.wrote_any is True
    assert result.json_path == json_path
    assert result.text_path == text_path
    assert result.manifest.artifact_count == 2
    assert json_path.exists()
    assert text_path.exists()


def test_backtest_export_service_exports_to_directory_with_default_names(
    tmp_path: Path,
) -> None:
    result = BacktestExportService().export_to_directory(
        make_summary(),
        directory=tmp_path,
    )

    assert result.wrote_any is True
    assert result.json_path == (
        tmp_path / "backtest_momentum_2024-01-01_2024-01-31.json"
    )
    assert result.text_path == (
        tmp_path / "backtest_momentum_2024-01-01_2024-01-31.txt"
    )
    assert result.manifest.artifact_count == 2
    assert result.json_path.exists()
    assert result.text_path.exists()


def test_backtest_export_service_exports_only_json_to_directory(
    tmp_path: Path,
) -> None:
    result = BacktestExportService().export_to_directory(
        make_summary(),
        directory=tmp_path,
        include_json=True,
        include_text=False,
    )

    assert result.wrote_any is True
    assert result.json_path == (
        tmp_path / "backtest_momentum_2024-01-01_2024-01-31.json"
    )
    assert result.text_path is None
    assert result.manifest.artifact_count == 1
    assert result.json_path.exists()


def test_backtest_export_service_exports_only_text_to_directory(
    tmp_path: Path,
) -> None:
    result = BacktestExportService().export_to_directory(
        make_summary(),
        directory=tmp_path,
        include_json=False,
        include_text=True,
    )

    assert result.wrote_any is True
    assert result.json_path is None
    assert result.text_path == (
        tmp_path / "backtest_momentum_2024-01-01_2024-01-31.txt"
    )
    assert result.manifest.artifact_count == 1
    assert result.text_path.exists()


def test_backtest_export_service_exports_nothing_when_no_formats_requested(
    tmp_path: Path,
) -> None:
    result = BacktestExportService().export_to_directory(
        make_summary(),
        directory=tmp_path,
        include_json=False,
        include_text=False,
    )

    assert result.wrote_any is False
    assert result.json_path is None
    assert result.text_path is None
    assert result.session is not None
    assert result.manifest.is_empty is True
