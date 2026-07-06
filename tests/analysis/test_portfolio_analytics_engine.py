from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.analysis.portfolio.engine import PortfolioAnalyticsEngine
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot


def test_portfolio_analytics_empty_snapshot() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("0"),
    )

    report = PortfolioAnalyticsEngine().analyze(snapshot)

    assert report.cash == Decimal("0")
    assert report.market_value == Decimal("0")
    assert report.total_equity == Decimal("0")
    assert report.gross_exposure == Decimal("0")
    assert report.net_exposure == Decimal("0")
    assert report.cash_weight == Decimal("0")
    assert report.gross_exposure_weight == Decimal("0")
    assert report.net_exposure_weight == Decimal("0")
    assert report.position_count == 0
    assert report.long_count == 0
    assert report.short_count == 0
    assert report.largest_position_symbol is None
    assert report.largest_position_weight == Decimal("0")


def test_portfolio_analytics_from_snapshot() -> None:
    snapshot = PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(UTC),
        cash=Decimal("10000"),
        positions=(
            PositionSnapshot(
                symbol="RELIANCE",
                quantity=10,
                average_price=Decimal("2500"),
            ),
            PositionSnapshot(
                symbol="TCS",
                quantity=5,
                average_price=Decimal("4000"),
            ),
        ),
    )

    report = PortfolioAnalyticsEngine().analyze(snapshot)

    assert report.cash == Decimal("10000")
    assert report.market_value == Decimal("45000")
    assert report.total_equity == Decimal("55000")
    assert report.gross_exposure == Decimal("45000")
    assert report.net_exposure == Decimal("45000")
    assert report.cash_weight == Decimal("10000") / Decimal("55000")
    assert report.gross_exposure_weight == Decimal("45000") / Decimal("55000")
    assert report.net_exposure_weight == Decimal("45000") / Decimal("55000")
    assert report.position_count == 2
    assert report.long_count == 2
    assert report.short_count == 0
    assert report.largest_position_symbol == "RELIANCE"
    assert report.largest_position_weight == Decimal("25000") / Decimal("55000")
