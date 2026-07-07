from __future__ import annotations

from decimal import Decimal

from alpha.backtest import BacktestEngine, BacktestOrder, BacktestResult


def test_backtest_result_keeps_backward_compatible_defaults() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("100000"),
        equity=Decimal("100000"),
        positions={},
        trades=(),
    )

    assert result.holdings_market_value == Decimal("0")
    assert result.reconciliation is None
    assert result.position_reports == ()
    assert result.trade_ledger == ()
    assert result.equity_curve == ()
    assert result.is_reconciled is True
    result.validate_reconciliation()


def test_backtest_engine_populates_financial_explainability_fields() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(BacktestOrder(symbol="RELIANCE", quantity=10),),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.ending_cash == Decimal("75000")
    assert result.holdings_market_value == Decimal("25000")
    assert result.equity == Decimal("100000")
    assert result.is_reconciled is True
    assert result.reconciliation is not None
    assert result.reconciliation.computed_equity == Decimal("100000")
    assert result.reconciliation.difference == Decimal("0")

    assert len(result.position_reports) == 1
    position = result.position_reports[0]
    assert position.symbol == "RELIANCE"
    assert position.quantity == 10
    assert position.entry_price == Decimal("2500")
    assert position.current_price == Decimal("2500")
    assert position.cost_basis == Decimal("25000")
    assert position.market_value == Decimal("25000")
    assert position.unrealized_pnl == Decimal("0")

    assert len(result.trade_ledger) == 1
    ledger_entry = result.trade_ledger[0]
    assert ledger_entry.side == "BUY"
    assert ledger_entry.running_cash == Decimal("75000")
    assert ledger_entry.cash_delta == Decimal("-25000")


def test_backtest_engine_reconciles_cash_and_holdings_after_sell() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(
            BacktestOrder(symbol="RELIANCE", quantity=10),
            BacktestOrder(symbol="RELIANCE", quantity=-4),
        ),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.ending_cash == Decimal("85000")
    assert result.holdings_market_value == Decimal("15000")
    assert result.equity == Decimal("100000")
    assert result.is_reconciled is True
    result.validate_reconciliation()

    assert result.positions == {"RELIANCE": 6}
    assert len(result.position_reports) == 1
    assert result.position_reports[0].quantity == 6
    assert result.position_reports[0].market_value == Decimal("15000")
    assert result.position_reports[0].realized_pnl == Decimal("0")
    assert len(result.trade_ledger) == 2
    assert [entry.side for entry in result.trade_ledger] == ["BUY", "SELL"]
