from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.portfolio.equity_curve import EquityCurve, EquityPoint
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot


def make_snapshot(
    timestamp: datetime,
    cash: Decimal,
    quantity: int,
    average_price: Decimal,
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=uuid4(),
        timestamp=timestamp,
        cash=cash,
        positions=(
            PositionSnapshot(
                symbol="RELIANCE",
                quantity=quantity,
                average_price=average_price,
            ),
        ),
    )


def test_equity_point_from_snapshot() -> None:
    timestamp = datetime.now(UTC)

    snapshot = make_snapshot(
        timestamp=timestamp,
        cash=Decimal("10000"),
        quantity=10,
        average_price=Decimal("2500"),
    )

    point = EquityPoint.from_snapshot(snapshot)

    assert point.timestamp == timestamp
    assert point.cash == Decimal("10000")
    assert point.market_value == Decimal("25000")
    assert point.equity == Decimal("35000")


def test_equity_curve_from_snapshots() -> None:
    start = datetime.now(UTC)

    curve = EquityCurve.from_snapshots(
        (
            make_snapshot(start, Decimal("10000"), 10, Decimal("100")),
            make_snapshot(
                start + timedelta(days=1),
                Decimal("10000"),
                10,
                Decimal("110"),
            ),
            make_snapshot(
                start + timedelta(days=2),
                Decimal("10000"),
                10,
                Decimal("105"),
            ),
        )
    )

    assert len(curve) == 3
    assert curve.starting_equity == Decimal("11000")
    assert curve.ending_equity == Decimal("11050")
    assert curve.total_return == Decimal("11050") / Decimal("11000") - Decimal("1")


def test_equity_curve_returns() -> None:
    start = datetime.now(UTC)

    curve = EquityCurve(
        (
            EquityPoint(
                timestamp=start,
                equity=Decimal("100"),
                cash=Decimal("0"),
                market_value=Decimal("100"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            ),
            EquityPoint(
                timestamp=start + timedelta(days=1),
                equity=Decimal("110"),
                cash=Decimal("0"),
                market_value=Decimal("110"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            ),
        )
    )

    assert curve.returns == (Decimal("0"), Decimal("0.1"))


def test_equity_curve_drawdowns() -> None:
    start = datetime.now(UTC)

    curve = EquityCurve(
        (
            EquityPoint(
                timestamp=start,
                equity=Decimal("100"),
                cash=Decimal("0"),
                market_value=Decimal("100"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            ),
            EquityPoint(
                timestamp=start + timedelta(days=1),
                equity=Decimal("120"),
                cash=Decimal("0"),
                market_value=Decimal("120"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            ),
            EquityPoint(
                timestamp=start + timedelta(days=2),
                equity=Decimal("90"),
                cash=Decimal("0"),
                market_value=Decimal("90"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            ),
        )
    )

    assert curve.high_water_marks == (
        Decimal("100"),
        Decimal("120"),
        Decimal("120"),
    )
    assert curve.drawdowns == (
        Decimal("0"),
        Decimal("0"),
        Decimal("90") / Decimal("120") - Decimal("1"),
    )
    assert curve.max_drawdown == Decimal("90") / Decimal("120") - Decimal("1")


def test_equity_curve_rejects_empty() -> None:
    with pytest.raises(ValueError):
        EquityCurve(())


def test_equity_curve_rejects_unordered_points() -> None:
    start = datetime.now(UTC)

    with pytest.raises(ValueError):
        EquityCurve(
            (
                EquityPoint(
                    timestamp=start,
                    equity=Decimal("100"),
                    cash=Decimal("0"),
                    market_value=Decimal("100"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                ),
                EquityPoint(
                    timestamp=start - timedelta(days=1),
                    equity=Decimal("90"),
                    cash=Decimal("0"),
                    market_value=Decimal("90"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                ),
            )
        )
