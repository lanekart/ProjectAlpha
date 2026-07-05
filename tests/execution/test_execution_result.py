from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alpha.execution.execution_result import ExecutionResult
from alpha.execution.fill import Fill


def test_success_result():
    fill = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        quantity=10,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )

    result = ExecutionResult(
        accepted=True,
        fills=(fill,),
    )

    assert result.total_quantity == 10
    assert result.average_price == Decimal("100")


def test_rejected_requires_reason():
    with pytest.raises(ValueError):
        ExecutionResult(
            accepted=False,
            rejection_reason=None,
        )


def test_rejected_cannot_have_fills():
    fill = Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        quantity=10,
        price=Decimal("100"),
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(ValueError):
        ExecutionResult(
            accepted=False,
            rejection_reason="invalid",
            fills=(fill,),
        )
