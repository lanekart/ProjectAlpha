from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.execution.fill import Fill


def test_valid_fill() -> None:
    fill = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol="AAPL",
        quantity=10,
        price=Decimal("2500"),
        timestamp=datetime.now(UTC),
    )

    assert fill.quantity == 10
    assert fill.symbol == "AAPL"


def test_invalid_price() -> None:
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="AAPL",
            quantity=10,
            price=Decimal("0"),
            timestamp=datetime.now(UTC),
        )


def test_negative_commission() -> None:
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="AAPL",
            quantity=10,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
            commission=Decimal("-1"),
        )


def test_negative_slippage() -> None:
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="AAPL",
            quantity=10,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
            slippage=Decimal("-0.01"),
        )


def test_empty_symbol() -> None:
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="",
            quantity=10,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
        )
