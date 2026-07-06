from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.backtest import BacktestOrder, BrokerSimulator


def test_broker_simulator_executes_buy_order() -> None:
    broker = BrokerSimulator()

    trade = broker.execute(
        order=BacktestOrder("RELIANCE", 10),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert trade is not None
    assert trade.symbol == "RELIANCE"
    assert trade.quantity == 10
    assert trade.price == Decimal("2500")
    assert trade.notional == Decimal("25000")


def test_broker_simulator_executes_sell_order() -> None:
    broker = BrokerSimulator()

    trade = broker.execute(
        order=BacktestOrder("RELIANCE", -4),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert trade is not None
    assert trade.symbol == "RELIANCE"
    assert trade.quantity == -4
    assert trade.price == Decimal("2500")
    assert trade.notional == Decimal("10000")


def test_broker_simulator_ignores_zero_quantity_order() -> None:
    broker = BrokerSimulator()

    trade = broker.execute(
        order=BacktestOrder("RELIANCE", 0),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert trade is None


def test_broker_simulator_rejects_missing_price() -> None:
    broker = BrokerSimulator()

    with pytest.raises(ValueError, match="missing price for symbol"):
        broker.execute(
            order=BacktestOrder("RELIANCE", 1),
            prices={},
        )


def test_broker_simulator_rejects_zero_price() -> None:
    broker = BrokerSimulator()

    with pytest.raises(ValueError, match="price must be greater than zero"):
        broker.execute(
            order=BacktestOrder("RELIANCE", 1),
            prices={"RELIANCE": Decimal("0")},
        )


def test_broker_simulator_rejects_negative_price() -> None:
    broker = BrokerSimulator()

    with pytest.raises(ValueError, match="price must be greater than zero"):
        broker.execute(
            order=BacktestOrder("RELIANCE", 1),
            prices={"RELIANCE": Decimal("-1")},
        )
