from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.execution.fill import Fill
from alpha.portfolio.portfolio_engine import PortfolioEngine

TEST_SYMBOL = "AAPL"


def make_fill() -> Fill:
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol=TEST_SYMBOL,
        quantity=100,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )


def test_apply_fill_creates_position() -> None:
    engine = PortfolioEngine()

    fill = make_fill()

    position = engine.apply_fill(fill)

    assert position.quantity == 100
    assert len(engine.positions()) == 1


def test_position_lookup() -> None:
    engine = PortfolioEngine()

    fill = make_fill()

    position = engine.apply_fill(fill)

    assert engine.position(position.symbol) == position


def test_symbols() -> None:
    engine = PortfolioEngine()

    fill = make_fill()

    position = engine.apply_fill(fill)

    assert engine.symbols() == (position.symbol,)


def test_snapshot_delegation() -> None:
    engine = PortfolioEngine()

    fill = make_fill()

    position = engine.apply_fill(fill)

    snapshot = engine.create_snapshot(position)

    assert snapshot.position_quantity == 100
