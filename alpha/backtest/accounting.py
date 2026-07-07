from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

_ZERO = Decimal("0")

BacktestTimestamp = date | datetime


@dataclass(frozen=True, slots=True)
class PortfolioReconciliation:
    """Portfolio-level accounting identity for a completed backtest.

    The core identity is:
        ending_cash + holdings_market_value == ending_equity

    A small tolerance is intentionally supported for future integrations that may
    quantize prices, fees, or external market values. The default remains exact.
    """

    starting_cash: Decimal
    ending_cash: Decimal
    holdings_market_value: Decimal
    ending_equity: Decimal
    tolerance: Decimal = _ZERO

    def __post_init__(self) -> None:
        if self.starting_cash < _ZERO:
            raise ValueError("starting_cash cannot be negative")
        if self.ending_cash < _ZERO:
            raise ValueError("ending_cash cannot be negative")
        if self.holdings_market_value < _ZERO:
            raise ValueError("holdings_market_value cannot be negative")
        if self.ending_equity < _ZERO:
            raise ValueError("ending_equity cannot be negative")
        if self.tolerance < _ZERO:
            raise ValueError("tolerance cannot be negative")

    @property
    def computed_equity(self) -> Decimal:
        return self.ending_cash + self.holdings_market_value

    @property
    def difference(self) -> Decimal:
        return self.ending_equity - self.computed_equity

    @property
    def is_balanced(self) -> bool:
        return abs(self.difference) <= self.tolerance

    def validate(self) -> None:
        if not self.is_balanced:
            raise ValueError(
                "portfolio reconciliation failed: "
                f"ending_cash({self.ending_cash}) + "
                f"holdings_market_value({self.holdings_market_value}) != "
                f"ending_equity({self.ending_equity}); "
                f"difference={self.difference}"
            )


@dataclass(frozen=True, slots=True)
class PositionReport:
    """Financially explainable open-position view."""

    symbol: str
    quantity: int
    entry_price: Decimal
    current_price: Decimal
    cost_basis: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = _ZERO
    entry_date: BacktestTimestamp | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.entry_price <= _ZERO:
            raise ValueError("entry_price must be greater than zero")
        if self.current_price <= _ZERO:
            raise ValueError("current_price must be greater than zero")
        if self.cost_basis < _ZERO:
            raise ValueError("cost_basis cannot be negative")
        if self.market_value < _ZERO:
            raise ValueError("market_value cannot be negative")

    @classmethod
    def from_prices(
        cls,
        *,
        symbol: str,
        quantity: int,
        entry_price: Decimal,
        current_price: Decimal,
        realized_pnl: Decimal = _ZERO,
        entry_date: BacktestTimestamp | None = None,
    ) -> PositionReport:
        cost_basis = entry_price * Decimal(quantity)
        market_value = current_price * Decimal(quantity)
        return cls(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            cost_basis=cost_basis,
            market_value=market_value,
            unrealized_pnl=market_value - cost_basis,
            realized_pnl=realized_pnl,
            entry_date=entry_date,
        )


@dataclass(frozen=True, slots=True)
class TradeLedgerEntry:
    """Auditable execution row with cash impact and running cash."""

    symbol: str
    side: str
    quantity: int
    price: Decimal
    fees: Decimal
    notional: Decimal
    cash_delta: Decimal
    running_cash: Decimal
    realized_pnl: Decimal = _ZERO
    timestamp: BacktestTimestamp | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.price <= _ZERO:
            raise ValueError("price must be greater than zero")
        if self.fees < _ZERO:
            raise ValueError("fees cannot be negative")
        if self.notional < _ZERO:
            raise ValueError("notional cannot be negative")

    @property
    def gross_amount(self) -> Decimal:
        return self.notional

    @property
    def net_amount(self) -> Decimal:
        if self.side == "BUY":
            return self.notional + self.fees
        return self.notional - self.fees

    @classmethod
    def buy(
        cls,
        *,
        symbol: str,
        quantity: int,
        price: Decimal,
        running_cash: Decimal,
        fees: Decimal = _ZERO,
        realized_pnl: Decimal = _ZERO,
        timestamp: BacktestTimestamp | None = None,
    ) -> TradeLedgerEntry:
        notional = price * Decimal(quantity)
        return cls(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=price,
            fees=fees,
            notional=notional,
            cash_delta=-(notional + fees),
            running_cash=running_cash,
            realized_pnl=realized_pnl,
            timestamp=timestamp,
        )

    @classmethod
    def sell(
        cls,
        *,
        symbol: str,
        quantity: int,
        price: Decimal,
        running_cash: Decimal,
        fees: Decimal = _ZERO,
        realized_pnl: Decimal = _ZERO,
        timestamp: BacktestTimestamp | None = None,
    ) -> TradeLedgerEntry:
        notional = price * Decimal(quantity)
        return cls(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            price=price,
            fees=fees,
            notional=notional,
            cash_delta=notional - fees,
            running_cash=running_cash,
            realized_pnl=realized_pnl,
            timestamp=timestamp,
        )


@dataclass(frozen=True, slots=True)
class EquityCurvePoint:
    """Daily mark-to-market portfolio state."""

    timestamp: BacktestTimestamp
    cash: Decimal
    holdings_market_value: Decimal
    equity: Decimal
    daily_return: Decimal
    drawdown: Decimal
    cumulative_return: Decimal

    def __post_init__(self) -> None:
        if self.cash < _ZERO:
            raise ValueError("cash cannot be negative")
        if self.holdings_market_value < _ZERO:
            raise ValueError("holdings_market_value cannot be negative")
        if self.equity < _ZERO:
            raise ValueError("equity cannot be negative")

    @property
    def computed_equity(self) -> Decimal:
        return self.cash + self.holdings_market_value

    @property
    def is_balanced(self) -> bool:
        return self.computed_equity == self.equity
