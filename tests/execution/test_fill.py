from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.execution.fill import Fill


def test_valid_fill():
    fill = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        quantity=10,
        price=Decimal("2500"),
        timestamp=datetime.now(UTC),
    )

    assert fill.quantity == 10


def test_invalid_price():
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            quantity=10,
            price=Decimal("0"),
            timestamp=datetime.now(UTC),
        )


def test_negative_commission():
    with pytest.raises(ValueError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            quantity=10,
            price=Decimal("100"),
            timestamp=datetime.now(UTC),
            commission=Decimal("-1"),
        )
