from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.execution.fill import Fill
from alpha.portfolio.accounting_engine import AccountingEngine

TEST_SYMBOL = "AAPL"


def make_fill(
    quantity: int,
    price: str,
) -> Fill:
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol=TEST_SYMBOL,
        quantity=quantity,
        price=Decimal(price),
        timestamp=datetime.now(UTC),
    )


def test_inventory_matches_position_quantity() -> None:
    engine = AccountingEngine()

    position = engine.apply_fill(
        None,
        make_fill(100, "100"),
    )

    inventory_quantity = sum(lot.quantity for lot in engine.inventory.open_lots())

    assert inventory_quantity == position.quantity


def test_fifo_consumption_reduces_inventory() -> None:
    engine = AccountingEngine()

    position = engine.apply_fill(
        None,
        make_fill(100, "100"),
    )

    realized = engine.inventory.consume_fifo(
        quantity=40,
        exit_price=Decimal("110"),
    )

    position.quantity -= 40
    position.realized_pnl += realized

    inventory_quantity = sum(lot.quantity for lot in engine.inventory.open_lots())

    assert inventory_quantity == 60
    assert position.quantity == 60


def test_flat_position_has_no_inventory() -> None:
    engine = AccountingEngine()

    position = engine.apply_fill(
        None,
        make_fill(100, "100"),
    )

    realized = engine.inventory.consume_fifo(
        quantity=100,
        exit_price=Decimal("110"),
    )

    position.quantity = 0
    position.realized_pnl += realized

    assert position.quantity == 0
    assert engine.inventory.open_lots() == ()


def test_average_price_never_negative() -> None:
    engine = AccountingEngine()

    position = engine.apply_fill(
        None,
        make_fill(100, "100"),
    )

    assert position.average_price >= Decimal("0")
