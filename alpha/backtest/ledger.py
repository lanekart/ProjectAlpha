from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.backtest.accounting import (
    BacktestTimestamp,
    PositionReport,
    TradeLedgerEntry,
)
from alpha.backtest.models import BacktestTrade

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LedgerState:
    cash: Decimal
    positions: dict[str, int]
    trades: tuple[BacktestTrade, ...]
    trade_ledger: tuple[TradeLedgerEntry, ...] = ()
    position_reports: tuple[PositionReport, ...] = ()
    realized_pnl_by_symbol: dict[str, Decimal] = field(default_factory=dict)

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def total_realized_pnl(self) -> Decimal:
        return sum(self.realized_pnl_by_symbol.values(), _ZERO)


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    quantity: int
    cost_basis: Decimal
    entry_date: BacktestTimestamp | None

    @property
    def average_cost(self) -> Decimal:
        if self.quantity <= 0:
            return _ZERO
        return self.cost_basis / Decimal(self.quantity)


class ExecutionLedger:
    def apply(
        self,
        *,
        starting_cash: Decimal,
        trades: tuple[BacktestTrade, ...],
        market_prices: dict[str, Decimal] | None = None,
    ) -> LedgerState:
        if starting_cash < _ZERO:
            raise ValueError("starting_cash cannot be negative")

        cash = starting_cash
        positions: dict[str, int] = {}
        open_positions: dict[str, _OpenPosition] = {}
        realized_pnl_by_symbol: dict[str, Decimal] = {}
        applied_trades: list[BacktestTrade] = []
        trade_ledger: list[TradeLedgerEntry] = []

        for trade in trades:
            if trade.quantity > 0:
                fees = self._trade_fees(trade)
                cash_required = trade.notional + fees
                if cash_required > cash:
                    raise ValueError("insufficient cash")

                cash -= cash_required
                current_quantity = positions.get(trade.symbol, 0)
                positions[trade.symbol] = current_quantity + trade.quantity
                open_positions[trade.symbol] = self._apply_buy_to_position(
                    existing=open_positions.get(trade.symbol),
                    trade=trade,
                    fees=fees,
                )
                trade_ledger.append(
                    TradeLedgerEntry.buy(
                        symbol=trade.symbol,
                        quantity=trade.quantity,
                        price=trade.price,
                        fees=fees,
                        realized_pnl=_ZERO,
                        running_cash=cash,
                        timestamp=self._trade_timestamp(trade),
                    )
                )

            elif trade.quantity < 0:
                current_quantity = positions.get(trade.symbol, 0)
                sell_quantity = abs(trade.quantity)

                if sell_quantity > current_quantity:
                    raise ValueError("cannot sell more than current position")

                fees = self._trade_fees(trade)
                realized_pnl = self._realized_pnl(
                    open_position=open_positions[trade.symbol],
                    trade=trade,
                    fees=fees,
                )
                cash += trade.notional - fees
                positions[trade.symbol] = current_quantity - sell_quantity
                realized_pnl_by_symbol[trade.symbol] = (
                    realized_pnl_by_symbol.get(trade.symbol, _ZERO) + realized_pnl
                )
                trade_ledger.append(
                    TradeLedgerEntry.sell(
                        symbol=trade.symbol,
                        quantity=sell_quantity,
                        price=trade.price,
                        fees=fees,
                        realized_pnl=realized_pnl,
                        running_cash=cash,
                        timestamp=self._trade_timestamp(trade),
                    )
                )

                open_positions[trade.symbol] = self._apply_sell_to_position(
                    existing=open_positions[trade.symbol],
                    sell_quantity=sell_quantity,
                )

                if positions[trade.symbol] == 0:
                    del positions[trade.symbol]
                    del open_positions[trade.symbol]
            else:
                continue

            applied_trades.append(trade)

        return LedgerState(
            cash=cash,
            positions=positions,
            trades=tuple(applied_trades),
            trade_ledger=tuple(trade_ledger),
            position_reports=self._position_reports(
                open_positions=open_positions,
                realized_pnl_by_symbol=realized_pnl_by_symbol,
                market_prices=market_prices or {},
            ),
            realized_pnl_by_symbol=realized_pnl_by_symbol,
        )

    def _apply_buy_to_position(
        self,
        *,
        existing: _OpenPosition | None,
        trade: BacktestTrade,
        fees: Decimal,
    ) -> _OpenPosition:
        trade_cost_basis = trade.notional + fees
        if existing is None:
            return _OpenPosition(
                quantity=trade.quantity,
                cost_basis=trade_cost_basis,
                entry_date=self._trade_timestamp(trade),
            )

        return _OpenPosition(
            quantity=existing.quantity + trade.quantity,
            cost_basis=existing.cost_basis + trade_cost_basis,
            entry_date=existing.entry_date,
        )

    def _apply_sell_to_position(
        self,
        *,
        existing: _OpenPosition,
        sell_quantity: int,
    ) -> _OpenPosition:
        remaining_quantity = existing.quantity - sell_quantity
        if remaining_quantity <= 0:
            return _OpenPosition(
                quantity=0,
                cost_basis=_ZERO,
                entry_date=existing.entry_date,
            )

        remaining_cost_basis = existing.average_cost * Decimal(remaining_quantity)
        return _OpenPosition(
            quantity=remaining_quantity,
            cost_basis=remaining_cost_basis,
            entry_date=existing.entry_date,
        )

    def _realized_pnl(
        self,
        *,
        open_position: _OpenPosition,
        trade: BacktestTrade,
        fees: Decimal,
    ) -> Decimal:
        sell_quantity = abs(trade.quantity)
        proceeds_after_fees = trade.notional - fees
        closed_cost_basis = open_position.average_cost * Decimal(sell_quantity)
        return proceeds_after_fees - closed_cost_basis

    def _position_reports(
        self,
        *,
        open_positions: dict[str, _OpenPosition],
        realized_pnl_by_symbol: dict[str, Decimal],
        market_prices: dict[str, Decimal],
    ) -> tuple[PositionReport, ...]:
        reports: list[PositionReport] = []

        for symbol in sorted(open_positions):
            open_position = open_positions[symbol]
            if open_position.quantity <= 0:
                continue

            current_price = market_prices.get(symbol, open_position.average_cost)
            market_value = current_price * Decimal(open_position.quantity)
            reports.append(
                PositionReport(
                    symbol=symbol,
                    quantity=open_position.quantity,
                    entry_price=open_position.average_cost,
                    current_price=current_price,
                    cost_basis=open_position.cost_basis,
                    market_value=market_value,
                    unrealized_pnl=market_value - open_position.cost_basis,
                    realized_pnl=realized_pnl_by_symbol.get(symbol, _ZERO),
                    entry_date=open_position.entry_date,
                )
            )

        return tuple(reports)

    def _trade_fees(self, trade: BacktestTrade) -> Decimal:
        fees = getattr(trade, "fees", _ZERO)
        if not isinstance(fees, Decimal):
            fees = Decimal(str(fees))
        if fees < _ZERO:
            raise ValueError("fees cannot be negative")
        return fees

    def _trade_timestamp(self, trade: BacktestTrade) -> BacktestTimestamp | None:
        timestamp = getattr(trade, "timestamp", None)
        if timestamp is None:
            return None
        return timestamp
