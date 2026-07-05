from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.ledger_event import LedgerEvent
from alpha.portfolio.portfolio_ledger import PortfolioLedger


def make_event() -> LedgerEvent:
    return LedgerEvent(
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


def test_append_event():
    ledger = PortfolioLedger()

    event = make_event()

    ledger.append(event)

    assert len(ledger) == 1
    assert ledger.last_event() == event


def test_events_are_returned_in_order():
    ledger = PortfolioLedger()

    first = make_event()
    second = make_event()

    ledger.append(first)
    ledger.append(second)

    events = ledger.events()

    assert events[0] == first
    assert events[1] == second


def test_empty_ledger():
    ledger = PortfolioLedger()

    assert len(ledger) == 0
    assert ledger.last_event() is None
    assert ledger.events() == ()
