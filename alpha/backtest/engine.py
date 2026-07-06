from __future__ import annotations

from decimal import Decimal

from alpha.backtest.broker import BrokerSimulator
from alpha.backtest.ledger import ExecutionLedger
from alpha.backtest.models import BacktestOrder, BacktestResult, BacktestTrade


class BacktestEngine:
    def __init__(
        self,
        *,
        broker: BrokerSimulator | None = None,
        ledger: ExecutionLedger | None = None,
    ) -> None:
        self._broker = broker or BrokerSimulator()
        self._ledger = ledger or ExecutionLedger()

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
        )

        equity = ledger_state.cash + self._mark_to_market(
            positions=ledger_state.positions,
            prices=prices,
        )

        return BacktestResult(
            starting_cash=starting_cash,
            ending_cash=ledger_state.cash,
            equity=equity,
            positions=ledger_state.positions,
            trades=ledger_state.trades,
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
