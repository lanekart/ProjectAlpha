from __future__ import annotations

from alpha.portfolio.portfolio import Portfolio
from alpha.portfolio.position import Position


class PortfolioManager:
    """
    High-level portfolio operations.

    G20:
    PortfolioManager no longer mutates lifecycle state.
    Lifecycle is determined directly from Position.quantity.
    """

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def open_position(self, position: Position) -> None:
        self.portfolio.add(position)

    def close_position(self, position: Position) -> None:
        """
        Archive a flat position.

        AccountingEngine is responsible for updating
        quantity and realized PnL.
        """
        if position.is_flat:
            self.portfolio.close(position)
