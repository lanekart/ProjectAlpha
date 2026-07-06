from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.backtest import BacktestTrade, ExecutionLedger


def make_trade(
    symbol: str,
    quantity: int,
    price: Decimal = Decimal("100"),
) -> BacktestTrade:
    return BacktestTrade(
        symbol=symbol,
        quantity=quantity,
        price=price,
        notional=price * Decimal(abs(quantity)),
    )


def test_execution_ledger_applies_buy_trade() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(make_trade("RELIANCE", 10, Decimal("2500")),),
    )

    assert state.cash == Decimal("75000")
    assert state.positions == {"RELIANCE": 10}
    assert state.trade_count == 1


def test_execution_ledger_applies_sell_trade() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("RELIANCE", 10, Decimal("2500")),
            make_trade("RELIANCE", -4, Decimal("2500")),
        ),
    )

    assert state.cash == Decimal("85000")
    assert state.positions == {"RELIANCE": 6}
    assert state.trade_count == 2


def test_execution_ledger_removes_flat_position() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("RELIANCE", 10, Decimal("2500")),
            make_trade("RELIANCE", -10, Decimal("2500")),
        ),
    )

    assert state.cash == Decimal("100000")
    assert state.positions == {}
    assert state.trade_count == 2


def test_execution_ledger_handles_multiple_symbols() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("RELIANCE", 10, Decimal("2500")),
            make_trade("TCS", 5, Decimal("4000")),
        ),
    )

    assert state.cash == Decimal("55000")
    assert state.positions == {
        "RELIANCE": 10,
        "TCS": 5,
    }


def test_execution_ledger_ignores_zero_quantity_trade() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(make_trade("RELIANCE", 0, Decimal("2500")),),
    )

    assert state.cash == Decimal("100000")
    assert state.positions == {}
    assert state.trades == ()


def test_execution_ledger_rejects_insufficient_cash() -> None:
    ledger = ExecutionLedger()

    with pytest.raises(ValueError, match="insufficient cash"):
        ledger.apply(
            starting_cash=Decimal("1000"),
            trades=(make_trade("RELIANCE", 10, Decimal("2500")),),
        )


def test_execution_ledger_rejects_oversell() -> None:
    ledger = ExecutionLedger()

    with pytest.raises(ValueError, match="cannot sell more than current position"):
        ledger.apply(
            starting_cash=Decimal("100000"),
            trades=(make_trade("RELIANCE", -1, Decimal("2500")),),
        )


def test_execution_ledger_rejects_negative_starting_cash() -> None:
    ledger = ExecutionLedger()

    with pytest.raises(ValueError, match="starting_cash cannot be negative"):
        ledger.apply(
            starting_cash=Decimal("-1"),
            trades=(),
        )
