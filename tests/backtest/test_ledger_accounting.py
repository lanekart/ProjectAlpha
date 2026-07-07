from __future__ import annotations

from decimal import Decimal

from alpha.backtest import BacktestTrade, ExecutionLedger


def make_trade(
    symbol: str,
    quantity: int,
    price: Decimal = Decimal("100"),
) -> BacktestTrade:
    return BacktestTrade(
        symbol=symbol,
        quantity=quantity,
        price=price,
        notional=price * Decimal(abs(quantity)),
    )


def test_execution_ledger_exposes_running_cash_ledger_entries() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("RELIANCE", 10, Decimal("2500")),
            make_trade("RELIANCE", -4, Decimal("2600")),
        ),
    )

    assert [entry.side for entry in state.trade_ledger] == ["BUY", "SELL"]
    assert [entry.running_cash for entry in state.trade_ledger] == [
        Decimal("75000"),
        Decimal("85400"),
    ]
    assert [entry.cash_delta for entry in state.trade_ledger] == [
        Decimal("-25000"),
        Decimal("10400"),
    ]


def test_execution_ledger_calculates_average_cost_and_realized_pnl() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("RELIANCE", 10, Decimal("100")),
            make_trade("RELIANCE", 10, Decimal("120")),
            make_trade("RELIANCE", -5, Decimal("150")),
        ),
        market_prices={"RELIANCE": Decimal("140")},
    )

    assert state.cash == Decimal("98550")
    assert state.positions == {"RELIANCE": 15}
    assert state.realized_pnl_by_symbol == {"RELIANCE": Decimal("200")}
    assert state.total_realized_pnl == Decimal("200")

    assert len(state.position_reports) == 1
    position = state.position_reports[0]
    assert position.symbol == "RELIANCE"
    assert position.quantity == 15
    assert position.entry_price == Decimal("110")
    assert position.current_price == Decimal("140")
    assert position.cost_basis == Decimal("1650")
    assert position.market_value == Decimal("2100")
    assert position.unrealized_pnl == Decimal("450")
    assert position.realized_pnl == Decimal("200")


def test_execution_ledger_tracks_realized_loss() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("TCS", 5, Decimal("4000")),
            make_trade("TCS", -2, Decimal("3900")),
        ),
    )

    assert state.realized_pnl_by_symbol == {"TCS": Decimal("-200")}
    assert state.total_realized_pnl == Decimal("-200")
    assert state.trade_ledger[-1].realized_pnl == Decimal("-200")


def test_execution_ledger_defaults_position_report_price_to_average_cost() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(make_trade("INFY", 4, Decimal("1500")),),
    )

    assert len(state.position_reports) == 1
    position = state.position_reports[0]
    assert position.current_price == Decimal("1500")
    assert position.market_value == Decimal("6000")
    assert position.unrealized_pnl == Decimal("0")


def test_execution_ledger_omits_closed_positions_from_position_reports() -> None:
    ledger = ExecutionLedger()

    state = ledger.apply(
        starting_cash=Decimal("100000"),
        trades=(
            make_trade("HDFCBANK", 3, Decimal("1700")),
            make_trade("HDFCBANK", -3, Decimal("1800")),
        ),
        market_prices={"HDFCBANK": Decimal("1900")},
    )

    assert state.positions == {}
    assert state.position_reports == ()
    assert state.realized_pnl_by_symbol == {"HDFCBANK": Decimal("300")}
