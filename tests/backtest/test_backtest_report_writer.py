from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.backtest import (
    BacktestReport,
    BacktestReportBuilder,
    BacktestReportWriter,
    PerformanceReport,
    StrategyStatisticsReport,
)


def make_report() -> BacktestReport:
    return BacktestReportBuilder().build(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
        processed_days=22,
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("100"),
        equity=Decimal("1100"),
        order_count=1,
        trade_count=2,
        position_count=1,
        positions={"AAPL": 10},
        performance=PerformanceReport(metrics={"total_return": Decimal("0.10")}),
        strategy_statistics=StrategyStatisticsReport(
            metrics={"recovery_factor": Decimal("2.5")}
        ),
    )


def test_backtest_report_writer_writes_json(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "report.json"
    report = make_report()

    written_path = BacktestReportWriter().write_json(report, output_path)

    assert written_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == report.as_dict()


def test_backtest_report_writer_writes_text(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "report.txt"

    written_path = BacktestReportWriter().write_text(make_report(), output_path)

    assert written_path == output_path
    content = output_path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert "Project Alpha Backtest" in content
    assert "Performance:" in content
    assert "Strategy Statistics:" in content


def test_backtest_report_writer_rejects_invalid_json_suffix(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="expected .json output path"):
        BacktestReportWriter().write_json(make_report(), tmp_path / "report.txt")


def test_backtest_report_writer_rejects_invalid_text_suffix(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="expected .txt output path"):
        BacktestReportWriter().write_text(make_report(), tmp_path / "report.json")
