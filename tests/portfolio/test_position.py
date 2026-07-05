from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.position import Position


def test_long_position() -> None:
    p = Position(
        position_id=uuid4(),
        symbol="RELIANCE",
        quantity=10,
        average_price=Decimal("100"),
        entry_time=datetime.now(UTC),
    )

    assert p.is_long
    assert not p.is_short
    assert not p.is_flat
    assert p.market_value == Decimal("1000")


def test_short_position() -> None:
    p = Position(
        position_id=uuid4(),
        symbol="TCS",
        quantity=-5,
        average_price=Decimal("200"),
        entry_time=datetime.now(UTC),
    )

    assert p.is_short
    assert not p.is_long
    assert p.market_value == Decimal("1000")


def test_flat_position() -> None:
    p = Position(
        position_id=uuid4(),
        symbol="INFY",
        quantity=0,
        average_price=Decimal("150"),
        entry_time=datetime.now(UTC),
    )

    assert p.is_flat
