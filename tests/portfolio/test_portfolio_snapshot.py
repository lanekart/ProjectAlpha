from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot


def test_position_snapshot_market_value() -> None:
    snapshot = PositionSnapshot(
        symbol="RELIANCE",
        quantity=10,
        average_price=Decimal("2500"),
        realized_pnl=Decimal("100"),
    )

    assert snapshot.market_value == Decimal("25000")


def test_portfolio_snapshot_aggregates_positions() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("10000"),
        positions=(
            PositionSnapshot(
                symbol="RELIANCE",
                quantity=10,
                average_price=Decimal("2500"),
                realized_pnl=Decimal("100"),
                unrealized_pnl=Decimal("50"),
            ),
            PositionSnapshot(
                symbol="TCS",
                quantity=5,
                average_price=Decimal("4000"),
                realized_pnl=Decimal("200"),
                unrealized_pnl=Decimal("-25"),
            ),
        ),
    )

    assert snapshot.market_value == Decimal("45000")
    assert snapshot.realized_pnl == Decimal("300")
    assert snapshot.unrealized_pnl == Decimal("25")
    assert snapshot.total_equity == Decimal("55000")
    assert snapshot.position_count == 2
    assert snapshot.symbols == ("RELIANCE", "TCS")
