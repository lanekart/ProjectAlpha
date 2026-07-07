from __future__ import annotations

import json
from decimal import Decimal

from alpha.backtest import (
    BacktestEngine,
    BacktestOrder,
    BacktestReportBuilder,
    BacktestReportRenderer,
    PerformanceAnalytics,
    PerformanceReport,
    StrategyStatisticsReport,
)


def test_financially_explainable_backtest_acceptance_flow() -> None:
    engine = BacktestEngine()

    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(
            BacktestOrder(symbol="RELIANCE", quantity=10),
            BacktestOrder(symbol="TCS", quantity=5),
            BacktestOrder(symbol="RELIANCE", quantity=-4),
        ),
        prices={
            "RELIANCE": Decimal("2500"),
            "TCS": Decimal("4000"),
        },
    )

    assert result.ending_cash == Decimal("65000")
    assert result.holdings_market_value == Decimal("35000")
    assert result.equity == Decimal("100000")
    assert result.is_reconciled is True
    result.validate_reconciliation()

    assert result.reconciliation is not None
    assert result.reconciliation.computed_equity == result.equity
    assert result.reconciliation.difference == Decimal("0")
    assert result.reconciliation.is_balanced is True

    assert result.positions == {
        "RELIANCE": 6,
        "TCS": 5,
    }
    assert len(result.position_reports) == 2

    reports_by_symbol = {report.symbol: report for report in result.position_reports}

    reliance = reports_by_symbol["RELIANCE"]
    assert reliance.quantity == 6
    assert reliance.entry_price == Decimal("2500")
    assert reliance.current_price == Decimal("2500")
    assert reliance.cost_basis == Decimal("15000")
    assert reliance.market_value == Decimal("15000")
    assert reliance.unrealized_pnl == Decimal("0")
    assert reliance.realized_pnl == Decimal("0")

    tcs = reports_by_symbol["TCS"]
    assert tcs.quantity == 5
    assert tcs.entry_price == Decimal("4000")
    assert tcs.current_price == Decimal("4000")
    assert tcs.cost_basis == Decimal("20000")
    assert tcs.market_value == Decimal("20000")
    assert tcs.unrealized_pnl == Decimal("0")
    assert tcs.realized_pnl == Decimal("0")

    assert [entry.side for entry in result.trade_ledger] == ["BUY", "BUY", "SELL"]
    assert [entry.running_cash for entry in result.trade_ledger] == [
        Decimal("75000"),
        Decimal("55000"),
        Decimal("65000"),
    ]
    assert [entry.cash_delta for entry in result.trade_ledger] == [
        Decimal("-25000"),
        Decimal("-20000"),
        Decimal("10000"),
    ]

    assert len(result.equity_curve) == 1
    equity_point = result.equity_curve[0]
    assert equity_point.cash == result.ending_cash
    assert equity_point.holdings_market_value == result.holdings_market_value
    assert equity_point.equity == result.equity
    assert equity_point.is_balanced is True

    summary = PerformanceAnalytics().summarize(result)
    assert summary.total_return == Decimal("0")
    assert summary.ending_equity == result.equity
    assert summary.cash_balance == result.ending_cash
    assert summary.exposure == Decimal("0.35")


def test_backtest_report_json_matches_financial_state() -> None:
    engine = BacktestEngine()
    result = engine.run(
        starting_cash=Decimal("100000"),
        orders=(BacktestOrder(symbol="RELIANCE", quantity=10),),
        prices={"RELIANCE": Decimal("2500")},
    )

    assert result.reconciliation is not None

    report = BacktestReportBuilder().build(
        strategy="momentum",
        start="2026-01-01",
        end="2026-01-31",
        processed_days=21,
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        holdings_market_value=result.holdings_market_value,
        equity=result.equity,
        order_count=1,
        trade_count=result.trade_count,
        position_count=len(result.positions),
        positions=result.positions,
        performance=PerformanceReport(
            metrics={
                "total_return": Decimal("0"),
                "exposure": Decimal("0.25"),
            }
        ),
        strategy_statistics=StrategyStatisticsReport(
            metrics={"trade_count": Decimal(str(result.trade_count))}
        ),
        reconciliation={
            "starting_cash": format(result.reconciliation.starting_cash, "f"),
            "ending_cash": format(result.reconciliation.ending_cash, "f"),
            "holdings_market_value": format(
                result.reconciliation.holdings_market_value,
                "f",
            ),
            "ending_equity": format(result.reconciliation.ending_equity, "f"),
            "computed_equity": format(result.reconciliation.computed_equity, "f"),
            "difference": format(result.reconciliation.difference, "f"),
            "is_balanced": str(result.reconciliation.is_balanced).lower(),
        },
        position_details=tuple(
            {
                "symbol": position.symbol,
                "quantity": str(position.quantity),
                "entry_price": format(position.entry_price, "f"),
                "current_price": format(position.current_price, "f"),
                "cost_basis": format(position.cost_basis, "f"),
                "market_value": format(position.market_value, "f"),
                "unrealized_pnl": format(position.unrealized_pnl, "f"),
                "realized_pnl": format(position.realized_pnl, "f"),
            }
            for position in result.position_reports
        ),
        trade_ledger=tuple(
            {
                "symbol": entry.symbol,
                "side": entry.side,
                "quantity": str(entry.quantity),
                "price": format(entry.price, "f"),
                "notional": format(entry.notional, "f"),
                "fees": format(entry.fees, "f"),
                "cash_delta": format(entry.cash_delta, "f"),
                "running_cash": format(entry.running_cash, "f"),
                "realized_pnl": format(entry.realized_pnl, "f"),
            }
            for entry in result.trade_ledger
        ),
        equity_curve=tuple(
            {
                "cash": format(point.cash, "f"),
                "holdings_market_value": format(point.holdings_market_value, "f"),
                "equity": format(point.equity, "f"),
                "daily_return": format(point.daily_return, "f"),
                "drawdown": format(point.drawdown, "f"),
                "cumulative_return": format(point.cumulative_return, "f"),
            }
            for point in result.equity_curve
        ),
    )

    payload = report.as_dict()
    json_payload = json.loads(report.as_json())

    assert json_payload == payload
    assert payload["metadata"]["starting_cash"] == "100000"
    assert payload["metadata"]["ending_cash"] == "75000"
    assert payload["metadata"]["holdings_market_value"] == "25000"
    assert payload["metadata"]["equity"] == "100000"

    assert payload["reconciliation"]["computed_equity"] == "100000"
    assert payload["reconciliation"]["difference"] == "0"
    assert payload["reconciliation"]["is_balanced"] == "true"

    assert payload["position_details"] == [
        {
            "symbol": "RELIANCE",
            "quantity": "10",
            "entry_price": "2500",
            "current_price": "2500",
            "cost_basis": "25000",
            "market_value": "25000",
            "unrealized_pnl": "0",
            "realized_pnl": "0",
        }
    ]
    assert payload["trade_ledger"] == [
        {
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "price": "2500",
            "notional": "25000",
            "fees": "0",
            "cash_delta": "-25000",
            "running_cash": "75000",
            "realized_pnl": "0",
        }
    ]
    assert payload["equity_curve"] == [
        {
            "cash": "75000",
            "holdings_market_value": "25000",
            "equity": "100000",
            "daily_return": "0",
            "drawdown": "0",
            "cumulative_return": "0",
        }
    ]

    rendered = BacktestReportRenderer().render(report)
    assert "Reconciliation:" in rendered
    assert "Position Details:" in rendered
    assert "Trade Ledger:" in rendered
    assert "Equity Curve:" in rendered
    assert "Holdings Value : 25000" in rendered
