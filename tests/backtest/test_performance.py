from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from alpha.backtest import (
    BacktestResult,
    BacktestTrade,
    PerformanceAnalytics,
    PerformanceSummary,
)


def test_performance_summary_is_immutable() -> None:
    summary = PerformanceSummary(
        total_return=Decimal("0.10"),
        cagr=Decimal("0.10"),
        volatility=Decimal("0.01"),
        sharpe_ratio=Decimal("1"),
        sortino_ratio=Decimal("1"),
        calmar_ratio=Decimal("1"),
        maximum_drawdown=Decimal("-0.05"),
        win_rate=Decimal("1"),
        profit_factor=Decimal("2"),
        average_win=Decimal("10"),
        average_loss=Decimal("-5"),
        expectancy=Decimal("10"),
        exposure=Decimal("0.25"),
        ending_equity=Decimal("110"),
        cash_balance=Decimal("80"),
    )

    with pytest.raises(FrozenInstanceError):
        summary.total_return = Decimal("0")  # type: ignore[misc]


def test_performance_analytics_summarizes_single_period_backtest_result() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("75000"),
        equity=Decimal("110000"),
        positions={"RELIANCE": 10},
        trades=(
            BacktestTrade(
                symbol="RELIANCE",
                quantity=10,
                price=Decimal("2500"),
                notional=Decimal("25000"),
            ),
        ),
    )

    summary = PerformanceAnalytics().summarize(result)

    assert summary.total_return == Decimal("0.10")
    assert summary.ending_equity == Decimal("110000")
    assert summary.cash_balance == Decimal("75000")
    assert summary.exposure == Decimal("35000") / Decimal("110000")
    assert summary.win_rate == Decimal("0")
    assert summary.profit_factor == Decimal("0")
    assert summary.average_win == Decimal("0")
    assert summary.average_loss == Decimal("0")
    assert summary.expectancy == Decimal("0")


def test_performance_analytics_computes_drawdown_and_ratios_from_equity_curve() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("120"),
        equity=Decimal("120"),
        positions={},
        trades=(),
    )

    summary = PerformanceAnalytics(periods_per_year=Decimal("4")).summarize(
        result,
        equity_curve=(
            Decimal("100"),
            Decimal("120"),
            Decimal("90"),
            Decimal("130"),
            Decimal("120"),
        ),
    )

    assert summary.total_return == Decimal("0.20")
    assert summary.maximum_drawdown == Decimal("-0.25")
    assert summary.volatility > Decimal("0")
    assert summary.sharpe_ratio != Decimal("0")
    assert summary.sortino_ratio != Decimal("0")
    assert summary.calmar_ratio != Decimal("0")


def test_performance_analytics_computes_realized_trade_statistics() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("100800"),
        equity=Decimal("100800"),
        positions={},
        trades=(
            BacktestTrade(
                symbol="ABC",
                quantity=10,
                price=Decimal("100"),
                notional=Decimal("1000"),
            ),
            BacktestTrade(
                symbol="ABC",
                quantity=-10,
                price=Decimal("120"),
                notional=Decimal("1200"),
            ),
            BacktestTrade(
                symbol="XYZ",
                quantity=10,
                price=Decimal("100"),
                notional=Decimal("1000"),
            ),
            BacktestTrade(
                symbol="XYZ",
                quantity=-10,
                price=Decimal("90"),
                notional=Decimal("900"),
            ),
        ),
    )

    summary = PerformanceAnalytics().summarize(result)

    assert summary.win_rate == Decimal("0.5")
    assert summary.profit_factor == Decimal("2")
    assert summary.average_win == Decimal("200")
    assert summary.average_loss == Decimal("-100")
    assert summary.expectancy == Decimal("50")


def test_performance_analytics_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="periods_per_year must be greater than zero"):
        PerformanceAnalytics(periods_per_year=Decimal("0"))


def test_performance_analytics_rejects_empty_equity_curve() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("100"),
        equity=Decimal("100"),
        positions={},
        trades=(),
    )

    with pytest.raises(ValueError, match="equity_curve cannot be empty"):
        PerformanceAnalytics().summarize(result, equity_curve=())


def test_performance_analytics_rejects_non_positive_equity_curve_value() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("100"),
        equity=Decimal("100"),
        positions={},
        trades=(),
    )

    with pytest.raises(
        ValueError,
        match="equity_curve values must be greater than zero",
    ):
        PerformanceAnalytics().summarize(
            result,
            equity_curve=(Decimal("100"), Decimal("0")),
        )
