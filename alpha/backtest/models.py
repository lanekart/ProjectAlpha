from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.backtest.accounting import (
    EquityCurvePoint,
    PortfolioReconciliation,
    PositionReport,
    TradeLedgerEntry,
)

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BacktestOrder:
    symbol: str
    quantity: int


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    symbol: str
    quantity: int
    price: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    starting_cash: Decimal
    ending_cash: Decimal
    equity: Decimal
    positions: dict[str, int]
    trades: tuple[BacktestTrade, ...]
    holdings_market_value: Decimal = _ZERO
    reconciliation: PortfolioReconciliation | None = None
    position_reports: tuple[PositionReport, ...] = ()
    trade_ledger: tuple[TradeLedgerEntry, ...] = ()
    equity_curve: tuple[EquityCurvePoint, ...] = ()

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def is_reconciled(self) -> bool:
        if self.reconciliation is None:
            return self.ending_cash + self.holdings_market_value == self.equity
        return self.reconciliation.is_balanced

    def validate_reconciliation(self) -> None:
        if self.reconciliation is not None:
            self.reconciliation.validate()
            return

        PortfolioReconciliation(
            starting_cash=self.starting_cash,
            ending_cash=self.ending_cash,
            holdings_market_value=self.holdings_market_value,
            ending_equity=self.equity,
        ).validate()
