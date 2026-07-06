from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.analysis.execution.engine import ExecutionAnalyticsEngine
from alpha.execution.fill import Fill


def make_fill(
    symbol: str,
    quantity: int,
    price: Decimal,
    commission: Decimal = Decimal("0"),
    slippage: Decimal = Decimal("0"),
) -> Fill:
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        symbol=symbol,
        quantity=quantity,
        price=price,
        timestamp=datetime.now(UTC),
        commission=commission,
        slippage=slippage,
    )


def test_execution_analytics_empty_fills() -> None:
    report = ExecutionAnalyticsEngine().analyze(())

    assert report.fill_count == 0
    assert report.symbol_count == 0
    assert report.total_quantity == 0
    assert report.gross_turnover == Decimal("0")
    assert report.average_fill_price == Decimal("0")
    assert report.total_commission == Decimal("0")
    assert report.total_slippage == Decimal("0")
    assert report.symbols == ()


def test_execution_analytics_from_fills() -> None:
    fills = (
        make_fill(
            symbol="RELIANCE",
            quantity=10,
            price=Decimal("2500"),
            commission=Decimal("20"),
            slippage=Decimal("5"),
        ),
        make_fill(
            symbol="TCS",
            quantity=5,
            price=Decimal("4000"),
            commission=Decimal("10"),
            slippage=Decimal("2"),
        ),
    )

    report = ExecutionAnalyticsEngine().analyze(fills)

    assert report.fill_count == 2
    assert report.symbol_count == 2
    assert report.total_quantity == 15
    assert report.gross_turnover == Decimal("45000")
    assert report.average_fill_price == Decimal("3000")
    assert report.total_commission == Decimal("30")
    assert report.total_slippage == Decimal("7")
    assert report.symbols == ("RELIANCE", "TCS")
