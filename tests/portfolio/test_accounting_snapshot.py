from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.accounting_engine import AccountingEngine
from alpha.portfolio.position import Position


def test_create_snapshot():
    engine = AccountingEngine()

    position = Position(
        position_id=uuid4(),
        symbol="RELIANCE",
        quantity=25,
        average_price=Decimal("2450"),
        realized_pnl=Decimal("350"),
        entry_time=datetime.now(UTC),
    )

    snapshot = engine.create_snapshot(position)

    assert snapshot.position_quantity == 25
    assert snapshot.average_price == Decimal("2450")
    assert snapshot.realized_pnl == Decimal("350")

    assert len(engine.snapshots) == 1
    assert engine.snapshots.latest() == snapshot
