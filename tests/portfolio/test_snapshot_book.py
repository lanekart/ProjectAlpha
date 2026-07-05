from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot
from alpha.portfolio.snapshot_book import SnapshotBook


def test_append_snapshot():
    book = SnapshotBook()

    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        position_quantity=50,
        average_price=Decimal("250"),
        realized_pnl=Decimal("100"),
    )

    book.append(snapshot)

    assert len(book) == 1
    assert book.latest() == snapshot


def test_empty_book():
    book = SnapshotBook()

    assert book.latest() is None
    assert len(book) == 0


def test_all_returns_tuple():
    book = SnapshotBook()

    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        position_quantity=10,
        average_price=Decimal("150"),
        realized_pnl=Decimal("0"),
    )

    book.append(snapshot)

    snapshots = book.all()

    assert isinstance(snapshots, tuple)
    assert snapshots[0] == snapshot
