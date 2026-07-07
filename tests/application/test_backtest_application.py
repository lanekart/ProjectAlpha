from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.application.backtest import BacktestSummary
from alpha.backtest.models import BacktestResult


def test_backtest_summary_exposes_stable_metrics() -> None:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("100"),
        equity=Decimal("1100"),
        positions={"AAPL": 10},
        trades=(),
    )

    summary = BacktestSummary(
        strategy=" Momentum ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        equity=result.equity,
        processed_days=22,
        order_count=1,
        trade_count=result.trade_count,
        position_count=1,
        positions=result.positions,
        result=result,
    )

    assert summary.strategy == "momentum"
    assert summary.total_return == Decimal("0.1")
    assert summary.position_count == 1
    assert summary.positions["AAPL"] == 10


def test_backtest_summary_rejects_position_count_mismatch() -> None:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("1000"),
        equity=Decimal("1000"),
        positions={},
        trades=(),
    )

    with pytest.raises(ValueError, match="position count"):
        BacktestSummary(
            strategy="momentum",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            starting_cash=result.starting_cash,
            ending_cash=result.ending_cash,
            equity=result.equity,
            processed_days=22,
            order_count=0,
            trade_count=0,
            position_count=1,
            positions=result.positions,
            result=result,
        )
