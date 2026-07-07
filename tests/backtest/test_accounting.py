from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.backtest.accounting import (
    EquityCurvePoint,
    PortfolioReconciliation,
    PositionReport,
    TradeLedgerEntry,
)


def test_portfolio_reconciliation_balances_cash_holdings_and_equity() -> None:
    reconciliation = PortfolioReconciliation(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("25000"),
        holdings_market_value=Decimal("82000"),
        ending_equity=Decimal("107000"),
    )

    assert reconciliation.computed_equity == Decimal("107000")
    assert reconciliation.difference == Decimal("0")
    assert reconciliation.is_balanced is True
    reconciliation.validate()


def test_portfolio_reconciliation_rejects_unbalanced_identity() -> None:
    reconciliation = PortfolioReconciliation(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("25000"),
        holdings_market_value=Decimal("82000"),
        ending_equity=Decimal("106999"),
    )

    assert reconciliation.is_balanced is False
    with pytest.raises(ValueError, match="portfolio reconciliation failed"):
        reconciliation.validate()


def test_position_report_calculates_cost_market_value_and_unrealized_pnl() -> None:
    position = PositionReport.from_prices(
        symbol="RELIANCE",
        quantity=10,
        entry_price=Decimal("2500"),
        current_price=Decimal("2600"),
        entry_date=date(2026, 7, 1),
    )

    assert position.cost_basis == Decimal("25000")
    assert position.market_value == Decimal("26000")
    assert position.unrealized_pnl == Decimal("1000")
    assert position.realized_pnl == Decimal("0")
    assert position.entry_date == date(2026, 7, 1)


def test_trade_ledger_entry_buy_calculates_cash_delta() -> None:
    entry = TradeLedgerEntry.buy(
        symbol="TCS",
        quantity=5,
        price=Decimal("4000"),
        fees=Decimal("10"),
        running_cash=Decimal("79990"),
    )

    assert entry.side == "BUY"
    assert entry.notional == Decimal("20000")
    assert entry.cash_delta == Decimal("-20010")
    assert entry.running_cash == Decimal("79990")


def test_trade_ledger_entry_sell_calculates_cash_delta() -> None:
    entry = TradeLedgerEntry.sell(
        symbol="TCS",
        quantity=5,
        price=Decimal("4100"),
        fees=Decimal("10"),
        realized_pnl=Decimal("500"),
        running_cash=Decimal("100490"),
    )

    assert entry.side == "SELL"
    assert entry.notional == Decimal("20500")
    assert entry.cash_delta == Decimal("20490")
    assert entry.realized_pnl == Decimal("500")


def test_equity_curve_point_exposes_daily_accounting_identity() -> None:
    point = EquityCurvePoint(
        timestamp=date(2026, 7, 7),
        cash=Decimal("25000"),
        holdings_market_value=Decimal("82000"),
        equity=Decimal("107000"),
        daily_return=Decimal("0.01"),
        drawdown=Decimal("0"),
        cumulative_return=Decimal("0.07"),
    )

    assert point.computed_equity == Decimal("107000")
    assert point.is_balanced is True


def test_financial_value_objects_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        PositionReport.from_prices(
            symbol="INFY",
            quantity=0,
            entry_price=Decimal("1500"),
            current_price=Decimal("1550"),
        )

    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        TradeLedgerEntry(
            symbol="INFY",
            side="HOLD",
            quantity=1,
            price=Decimal("1500"),
            fees=Decimal("0"),
            notional=Decimal("1500"),
            cash_delta=Decimal("0"),
            running_cash=Decimal("100000"),
        )
