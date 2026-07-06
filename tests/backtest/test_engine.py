from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.backtest import BacktestEngine, BacktestOrder


def test_backtest_engine_buys_position_and_marks_equity() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(BacktestOrder("RELIANCE", 10),),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.ending_cash == Decimal("75000")
    assert result.positions == {"RELIANCE": 10}
    assert result.equity == Decimal("100000")
    assert result.trade_count == 1


def test_backtest_engine_sells_existing_position() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(
            BacktestOrder("RELIANCE", 10),
            BacktestOrder("RELIANCE", -4),
        ),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.ending_cash == Decimal("85000")
    assert result.positions == {"RELIANCE": 6}
    assert result.equity == Decimal("100000")
    assert result.trade_count == 2


def test_backtest_engine_removes_flat_position() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(
            BacktestOrder("RELIANCE", 10),
            BacktestOrder("RELIANCE", -10),
        ),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.ending_cash == Decimal("100000")
    assert result.positions == {}
    assert result.equity == Decimal("100000")


def test_backtest_engine_rejects_insufficient_cash() -> None:
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="insufficient cash"):
        engine.run(
            starting_cash=Decimal("1000"),
            orders=(BacktestOrder("RELIANCE", 10),),
            prices={"RELIANCE": Decimal("2500")},
        )


def test_backtest_engine_rejects_oversell() -> None:
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="cannot sell more than current position"):
        engine.run(
            starting_cash=Decimal("100000"),
            orders=(BacktestOrder("RELIANCE", -1),),
            prices={"RELIANCE": Decimal("2500")},
        )


def test_backtest_engine_rejects_missing_price() -> None:
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="missing price for symbol"):
        engine.run(
            starting_cash=Decimal("100000"),
            orders=(BacktestOrder("RELIANCE", 1),),
            prices={},
        )


def test_backtest_engine_rejects_non_positive_price() -> None:
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="price must be greater than zero"):
        engine.run(
            starting_cash=Decimal("100000"),
            orders=(BacktestOrder("RELIANCE", 1),),
            prices={"RELIANCE": Decimal("0")},
        )


def test_backtest_engine_rejects_negative_starting_cash() -> None:
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="starting_cash cannot be negative"):
        engine.run(
            starting_cash=Decimal("-1"),
            orders=(),
            prices={},
        )
