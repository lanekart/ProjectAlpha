from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.portfolio_book import PortfolioBook
from alpha.portfolio.position import Position


def make_position(symbol: str) -> Position:
    return Position(
        position_id=uuid4(),
        symbol=symbol,
        quantity=100,
        average_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        entry_time=datetime.now(UTC),
    )


def test_add_position() -> None:
    book = PortfolioBook()

    position = make_position("AAPL")

    book.add(position)

    assert book.get("AAPL") == position


def test_contains_symbol() -> None:
    book = PortfolioBook()

    book.add(make_position("MSFT"))

    assert book.contains("MSFT")
    assert not book.contains("AAPL")


def test_positions_are_immutable() -> None:
    book = PortfolioBook()

    book.add(make_position("AAPL"))
    book.add(make_position("MSFT"))

    positions = book.positions()

    assert len(positions) == 2

    assert isinstance(positions, tuple)


def test_symbols() -> None:
    book = PortfolioBook()

    book.add(make_position("AAPL"))
    book.add(make_position("NVDA"))

    symbols = set(book.symbols())

    assert symbols == {"AAPL", "NVDA"}
