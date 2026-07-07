from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.backtest.accounting import PortfolioReconciliation
from alpha.backtest.broker import BrokerSimulator
from alpha.backtest.equity_curve import EquityCurveBuilder
from alpha.backtest.ledger import ExecutionLedger
from alpha.backtest.models import BacktestOrder, BacktestResult, BacktestTrade


class BacktestEngine:
    def __init__(
        self,
        *,
        broker: BrokerSimulator | None = None,
        ledger: ExecutionLedger | None = None,
        equity_curve_builder: EquityCurveBuilder | None = None,
    ) -> None:
        self._broker = broker or BrokerSimulator()
        self._ledger = ledger or ExecutionLedger()
        self._equity_curve_builder = equity_curve_builder or EquityCurveBuilder()

    def run(
        self,
        *,
        starting_cash: Decimal,
        orders: tuple[BacktestOrder, ...],
        prices: dict[str, Decimal],
    ) -> BacktestResult:
        trades = self._execute_orders(orders=orders, prices=prices)

        ledger_state = self._ledger.apply(
            starting_cash=starting_cash,
            trades=trades,
            market_prices=prices,
        )

        holdings_market_value = self._mark_to_market(
            positions=ledger_state.positions,
            prices=prices,
        )
        equity = ledger_state.cash + holdings_market_value
        reconciliation = PortfolioReconciliation(
            starting_cash=starting_cash,
            ending_cash=ledger_state.cash,
            holdings_market_value=holdings_market_value,
            ending_equity=equity,
        )
        reconciliation.validate()

        return BacktestResult(
            starting_cash=starting_cash,
            ending_cash=ledger_state.cash,
            equity=equity,
            positions=ledger_state.positions,
            trades=ledger_state.trades,
            holdings_market_value=holdings_market_value,
            reconciliation=reconciliation,
            position_reports=ledger_state.position_reports,
            trade_ledger=ledger_state.trade_ledger,
            equity_curve=self._equity_curve_builder.single_point(
                timestamp=date.today(),
                starting_cash=starting_cash,
                ending_cash=ledger_state.cash,
                holdings_market_value=holdings_market_value,
            ),
        )

    def _execute_orders(
        self,
        *,
        orders: tuple[BacktestOrder, ...],
        prices: dict[str, Decimal],
    ) -> tuple[BacktestTrade, ...]:
        trades: list[BacktestTrade] = []

        for order in orders:
            trade = self._broker.execute(order=order, prices=prices)

            if trade is not None:
                trades.append(trade)

        return tuple(trades)

    def _mark_to_market(
        self,
        *,
        positions: dict[str, int],
        prices: dict[str, Decimal],
    ) -> Decimal:
        market_value = Decimal("0")

        for symbol, quantity in positions.items():
            trade = self._broker.execute(
                order=BacktestOrder(symbol=symbol, quantity=quantity),
                prices=prices,
            )

            if trade is None:
                continue

            market_value += trade.notional

        return market_value
