from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.portfolio.closed_trade import ClosedTrade


def test_closed_trade_properties() -> None:
    trade = ClosedTrade(
        trade_id=uuid4(),
        symbol="RELIANCE",
        entry_time=datetime.now(UTC),
        exit_time=datetime.now(UTC),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        quantity=10,
        realized_pnl=Decimal("100"),
        commission=Decimal("5"),
        slippage=Decimal("2"),
    )

    assert trade.gross_value == Decimal("1000")
    assert trade.net_pnl == Decimal("93")


def test_closed_trade_is_immutable() -> None:
    trade = ClosedTrade(
        trade_id=uuid4(),
        symbol="TCS",
        entry_time=datetime.now(UTC),
        exit_time=datetime.now(UTC),
        entry_price=Decimal("100"),
        exit_price=Decimal("120"),
        quantity=5,
        realized_pnl=Decimal("100"),
    )

    try:
        trade.quantity = 10
        assert False
    except Exception:
        assert True
