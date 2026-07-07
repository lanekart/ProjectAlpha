from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.backtest import BacktestEngine, BacktestOrder, EquityCurveBuilder


def test_equity_curve_builder_returns_empty_curve_for_no_points() -> None:
    builder = EquityCurveBuilder()

    curve = builder.build(starting_cash=Decimal("100000"), points=())

    assert curve == ()


def test_equity_curve_builder_calculates_returns() -> None:
    builder = EquityCurveBuilder()

    curve = builder.build(
        starting_cash=Decimal("100000"),
        points=(
            (date(2026, 1, 1), Decimal("90000"), Decimal("15000")),
            (date(2026, 1, 2), Decimal("88000"), Decimal("12000")),
            (date(2026, 1, 3), Decimal("85000"), Decimal("20000")),
        ),
    )

    assert [point.equity for point in curve] == [
        Decimal("105000"),
        Decimal("100000"),
        Decimal("105000"),
    ]
    assert curve[0].daily_return == Decimal("0.05")
    assert curve[0].drawdown == Decimal("0")
    assert curve[0].cumulative_return == Decimal("0.05")

    assert curve[1].daily_return == Decimal("-0.04761904761904761904761904762")
    assert curve[1].drawdown == Decimal("-0.04761904761904761904761904762")
    assert curve[1].cumulative_return == Decimal("0")

    assert curve[2].daily_return == Decimal("0.05")
    assert curve[2].drawdown == Decimal("0")
    assert curve[2].cumulative_return == Decimal("0.05")

    assert all(point.is_balanced for point in curve)


def test_equity_curve_builder_rejects_non_positive_starting_cash() -> None:
    builder = EquityCurveBuilder()

    with pytest.raises(ValueError, match="starting_cash must be greater than zero"):
        builder.build(starting_cash=Decimal("0"), points=())


def test_equity_curve_builder_rejects_negative_cash() -> None:
    builder = EquityCurveBuilder()

    with pytest.raises(ValueError, match="cash cannot be negative"):
        builder.build(
            starting_cash=Decimal("100000"),
            points=((date(2026, 1, 1), Decimal("-1"), Decimal("0")),),
        )


def test_backtest_engine_populates_balanced_equity_curve_point() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(BacktestOrder(symbol="RELIANCE", quantity=10),),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert len(result.equity_curve) == 1
    point = result.equity_curve[0]
    assert point.cash == Decimal("75000")
    assert point.holdings_market_value == Decimal("25000")
    assert point.equity == Decimal("100000")
    assert point.daily_return == Decimal("0")
    assert point.drawdown == Decimal("0")
    assert point.cumulative_return == Decimal("0")
    assert point.is_balanced is True
