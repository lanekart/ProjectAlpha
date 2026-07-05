from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.portfolio.ledger_event import LedgerEvent


def test_valid_event():
    event = LedgerEvent(
        event_id=uuid4(),
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol="INFY",
        quantity=100,
        price=Decimal("1500"),
        realized_pnl=Decimal("0"),
        position_quantity=100,
        average_price=Decimal("1500"),
        timestamp=datetime.now(UTC),
    )

    assert event.symbol == "INFY"
    assert event.quantity == 100
    assert event.average_price == Decimal("1500")


def test_price_must_be_positive():
    with pytest.raises(ValueError):
        LedgerEvent(
            event_id=uuid4(),
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="INFY",
            quantity=100,
            price=Decimal("0"),
            realized_pnl=Decimal("0"),
            position_quantity=100,
            average_price=Decimal("1500"),
            timestamp=datetime.now(UTC),
        )


def test_average_price_cannot_be_negative():
    with pytest.raises(ValueError):
        LedgerEvent(
            event_id=uuid4(),
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="INFY",
            quantity=100,
            price=Decimal("1500"),
            realized_pnl=Decimal("0"),
            position_quantity=100,
            average_price=Decimal("-1"),
            timestamp=datetime.now(UTC),
        )
