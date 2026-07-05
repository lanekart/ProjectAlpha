from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


def test_snapshot_creation():
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        position_quantity=125,
        average_price=Decimal("1834.25"),
        realized_pnl=Decimal("2450.50"),
    )

    assert snapshot.position_quantity == 125
    assert snapshot.average_price == Decimal("1834.25")
    assert snapshot.realized_pnl == Decimal("2450.50")
