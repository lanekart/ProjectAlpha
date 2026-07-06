from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.execution.fill import Fill
from alpha.portfolio.accounting_engine import AccountingEngine

TEST_SYMBOL = "AAPL"


def test_apply_fill_creates_ledger_event() -> None:
    engine = AccountingEngine()

    fill = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol=TEST_SYMBOL,
        quantity=100,
        price=Decimal("150"),
        timestamp=datetime.now(UTC),
    )

    position = engine.apply_fill(None, fill)

    assert position.quantity == 100

    assert len(engine.ledger) == 1

    event = engine.ledger.last_event()

    assert event is not None
    assert event.fill_id == fill.fill_id
    assert event.order_id == fill.order_id
    assert event.quantity == 100
    assert event.position_quantity == 100
    assert event.average_price == Decimal("150")
