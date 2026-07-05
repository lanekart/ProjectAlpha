from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.portfolio.inventory import InventoryLot
from alpha.portfolio.inventory_book import InventoryBook


def test_fifo_single_lot() -> None:
    book = InventoryBook()

    book.add_lot(
        InventoryLot(
            fill_id=uuid4(),
            quantity=100,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
        )
    )

    pnl = book.consume_fifo(
        quantity=40,
        exit_price=Decimal("120"),
    )

    assert pnl == Decimal("800")
    assert book.remaining_quantity() == 60


def test_fifo_multiple_lots() -> None:
    book = InventoryBook()

    book.add_lot(
        InventoryLot(
            fill_id=uuid4(),
            quantity=100,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
        )
    )

    book.add_lot(
        InventoryLot(
            fill_id=uuid4(),
            quantity=50,
            price=Decimal("110"),
            timestamp=datetime.now(UTC),
        )
    )

    pnl = book.consume_fifo(
        quantity=120,
        exit_price=Decimal("130"),
    )

    assert pnl == Decimal("3400")
    assert book.remaining_quantity() == 30

    remaining = book.open_lots()

    assert len(remaining) == 1
    assert remaining[0].quantity == 30
    assert remaining[0].price == Decimal("110")


def test_fifo_insufficient_inventory() -> None:
    book = InventoryBook()

    with pytest.raises(ValueError):
        book.consume_fifo(
            quantity=1,
            exit_price=Decimal("100"),
        )
