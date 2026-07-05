from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.portfolio.enums import ExitReason, PositionStatus
from alpha.portfolio.portfolio import Portfolio
from alpha.portfolio.position import Position


class PortfolioManager:
    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    def open_position(self, position: Position) -> None:
        self.portfolio.add(position)

    def close_position(
        self,
        position: Position,
        price: Decimal,
        reason: ExitReason,
        exit_date: date,
    ) -> None:
        position.exit_price = price
        position.exit_date = exit_date
        position.status = PositionStatus.CLOSED
        position.exit_reason = reason

        position.realized_pnl = (price - position.entry_price) * Decimal(
            position.quantity
        )

        self.portfolio.close(position)
