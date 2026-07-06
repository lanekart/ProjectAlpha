from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """
    Immutable snapshot of one portfolio position.
    """

    symbol: str
    quantity: int
    average_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    @property
    def market_value(self) -> Decimal:
        return self.average_price * Decimal(abs(self.quantity))


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """
    Immutable checkpoint of complete portfolio state.
    """

    snapshot_id: UUID
    timestamp: datetime
    cash: Decimal
    positions: tuple[PositionSnapshot, ...] = ()

    @property
    def market_value(self) -> Decimal:
        return sum(
            (position.market_value for position in self.positions),
            Decimal("0"),
        )

    @property
    def realized_pnl(self) -> Decimal:
        return sum(
            (position.realized_pnl for position in self.positions),
            Decimal("0"),
        )

    @property
    def unrealized_pnl(self) -> Decimal:
        return sum(
            (position.unrealized_pnl for position in self.positions),
            Decimal("0"),
        )

    @property
    def total_equity(self) -> Decimal:
        return self.cash + self.market_value

    @property
    def gross_exposure(self) -> Decimal:
        return self.market_value

    @property
    def net_exposure(self) -> Decimal:
        return sum(
            (
                position.average_price * Decimal(position.quantity)
                for position in self.positions
            ),
            Decimal("0"),
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(position.symbol for position in self.positions)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def position_quantity(self) -> int:
        return sum(position.quantity for position in self.positions)

    @property
    def average_price(self) -> Decimal:
        if not self.positions:
            return Decimal("0")

        total_quantity = sum(abs(position.quantity) for position in self.positions)

        if total_quantity == 0:
            return Decimal("0")

        total_cost = sum(
            (
                position.average_price * Decimal(abs(position.quantity))
                for position in self.positions
            ),
            Decimal("0"),
        )

        return total_cost / Decimal(total_quantity)
