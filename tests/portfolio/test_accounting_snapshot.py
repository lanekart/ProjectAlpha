from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.accounting_engine import AccountingEngine
from alpha.portfolio.position import Position


def test_create_snapshot() -> None:
    engine = AccountingEngine()

    position = Position(
        position_id=uuid4(),
        symbol="RELIANCE",
        quantity=25,
        average_price=Decimal("2450"),
        realized_pnl=Decimal("350"),
        entry_time=datetime.now(UTC),
    )

    snapshot = engine.create_snapshot(
        positions=(position,),
        cash=Decimal("10000"),
    )

    assert snapshot.cash == Decimal("10000")
    assert snapshot.position_count == 1
    assert snapshot.positions[0].symbol == "RELIANCE"
    assert snapshot.positions[0].quantity == 25
    assert snapshot.positions[0].average_price == Decimal("2450")
    assert snapshot.realized_pnl == Decimal("350")

    assert len(engine.snapshots) == 1
    assert engine.snapshots.latest() == snapshot
