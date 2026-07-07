from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from alpha.backtest import (
    BacktestReport,
    BacktestReportBuilder,
    BacktestReportRenderer,
    PerformanceReport,
    StrategyStatisticsReport,
)


def make_performance_report() -> PerformanceReport:
    return PerformanceReport(metrics={"total_return": Decimal("0.10")})


def make_strategy_statistics_report() -> StrategyStatisticsReport:
    return StrategyStatisticsReport(metrics={"recovery_factor": Decimal("2.5")})


def make_backtest_report() -> BacktestReport:
    return BacktestReportBuilder().build(
        strategy=" Momentum ",
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
        performance=make_performance_report(),
        strategy_statistics=make_strategy_statistics_report(),
    )


def test_backtest_report_is_immutable_and_serializable() -> None:
    report = make_backtest_report()

    assert report.as_dict() == {
        "metadata": {
            "strategy": "momentum",
            "start": "2024-01-01",
            "end": "2024-01-31",
            "processed_days": "22",
            "starting_cash": "1000",
            "ending_cash": "100",
            "equity": "1100",
        },
        "performance": {"total_return": "0.10"},
        "strategy_statistics": {"recovery_factor": "2.5"},
        "execution": {
            "orders": 1,
            "trades": 2,
            "positions": 1,
        },
        "positions": {"AAPL": 10},
    }

    with pytest.raises(FrozenInstanceError):
        report.positions = {}  # type: ignore[misc]

    with pytest.raises(TypeError):
        report.positions["AAPL"] = 0  # type: ignore[index]


def test_backtest_report_exports_deterministic_json() -> None:
    report = make_backtest_report()

    payload = json.loads(report.as_json())

    assert payload == report.as_dict()
    assert report.as_json() == json.dumps(
        report.as_dict(),
        sort_keys=True,
    )


def test_backtest_report_exports_pretty_json() -> None:
    report = make_backtest_report()

    payload = report.as_json(indent=2)

    assert "\n" in payload
    assert json.loads(payload) == report.as_dict()


def test_backtest_report_renderer_outputs_complete_text_report() -> None:
    report = make_backtest_report()

    assert BacktestReportRenderer().render(report) == (
        "Project Alpha Backtest",
        "",
        "Strategy       : momentum",
        "Start          : 2024-01-01",
        "End            : 2024-01-31",
        "Processed Days : 22",
        "Starting Cash  : 1000",
        "Ending Cash    : 100",
        "Equity         : 1100",
        "",
        "Performance:",
        "Total Return    : 0.10",
        "",
        "Strategy Statistics:",
        "Recovery Factor       : 2.5",
        "",
        "Execution:",
        "Orders         : 1",
        "Trades         : 2",
        "Positions      : 1",
        "",
        "Positions:",
        "AAPL: 10",
    )


def test_backtest_report_renderer_handles_empty_positions() -> None:
    report = BacktestReportBuilder().build(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
        processed_days=22,
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("1000"),
        equity=Decimal("1000"),
        order_count=0,
        trade_count=0,
        position_count=0,
        positions={},
        performance=make_performance_report(),
        strategy_statistics=make_strategy_statistics_report(),
    )

    assert BacktestReportRenderer().render(report)[-1] == "Positions: none"


def test_backtest_report_builder_rejects_invalid_inputs() -> None:
    builder = BacktestReportBuilder()

    with pytest.raises(ValueError, match="strategy cannot be empty"):
        builder.build(
            strategy=" ",
            start="2024-01-01",
            end="2024-01-31",
            processed_days=22,
            starting_cash=Decimal("1000"),
            ending_cash=Decimal("100"),
            equity=Decimal("1100"),
            order_count=1,
            trade_count=2,
            position_count=0,
            positions={},
            performance=make_performance_report(),
            strategy_statistics=make_strategy_statistics_report(),
        )

    with pytest.raises(ValueError, match="position_count must match positions"):
        builder.build(
            strategy="momentum",
            start="2024-01-01",
            end="2024-01-31",
            processed_days=22,
            starting_cash=Decimal("1000"),
            ending_cash=Decimal("100"),
            equity=Decimal("1100"),
            order_count=1,
            trade_count=2,
            position_count=2,
            positions={"AAPL": 10},
            performance=make_performance_report(),
            strategy_statistics=make_strategy_statistics_report(),
        )
