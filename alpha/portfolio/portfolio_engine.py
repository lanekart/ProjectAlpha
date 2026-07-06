from __future__ import annotations

from dataclasses import dataclass, field

from alpha.execution.fill import Fill
from alpha.portfolio.accounting_engine import AccountingEngine
from alpha.portfolio.portfolio_book import PortfolioBook
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot
from alpha.portfolio.position import Position


@dataclass
class PortfolioEngine:
    """
    Institutional portfolio orchestration engine.

    Responsibilities
    ----------------
    - Own the PortfolioBook
    - Route fills to AccountingEngine
    - Keep portfolio positions synchronized
    - Expose portfolio queries

    AccountingEngine remains responsible only for accounting logic.
    """

    accounting: AccountingEngine = field(default_factory=AccountingEngine)
    portfolio: PortfolioBook = field(default_factory=PortfolioBook)

    def apply_fill(self, fill: Fill) -> Position:
        """
        Apply an execution fill to the portfolio.

        The PortfolioEngine locates the existing position (if any),
        delegates accounting to AccountingEngine, stores the updated
        position, and returns it.
        """

        position = self.portfolio.get(str(fill.order_id))

        updated = self.accounting.apply_fill(
            position,
            fill,
        )

        self.portfolio.add(updated)

        return updated

    def position(
        self,
        symbol: str,
    ) -> Position | None:
        """
        Return the current position for a symbol.
        """

        return self.portfolio.get(symbol)

    def positions(self) -> tuple[Position, ...]:
        """
        Return all current portfolio positions.
        """

        return self.portfolio.positions()

    def symbols(self) -> tuple[str, ...]:
        """
        Return every symbol currently tracked.
        """

        return self.portfolio.symbols()

    def create_snapshot(
        self,
        position: Position,
    ) -> PortfolioSnapshot:
        """
        Delegate snapshot creation to the accounting engine.
        """

        return self.accounting.create_snapshot(position)
