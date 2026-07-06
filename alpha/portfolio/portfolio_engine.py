from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alpha.execution.fill import Fill
from alpha.portfolio.accounting_engine import AccountingEngine
from alpha.portfolio.portfolio_book import PortfolioBook
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot
from alpha.portfolio.position import Position


@dataclass
class PortfolioEngine:
    """
    Institutional portfolio orchestration engine.
    """

    accounting: AccountingEngine = field(default_factory=AccountingEngine)
    portfolio: PortfolioBook = field(default_factory=PortfolioBook)
    cash: Decimal = Decimal("0")

    def apply_fill(self, fill: Fill) -> Position:
        position = self.portfolio.get(fill.symbol)

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
        return self.portfolio.get(symbol)

    def positions(self) -> tuple[Position, ...]:
        return self.portfolio.positions()

    def symbols(self) -> tuple[str, ...]:
        return self.portfolio.symbols()

    def create_snapshot(
        self,
        position: Position | None = None,
    ) -> PortfolioSnapshot:
        positions = (position,) if position is not None else self.positions()

        return self.accounting.create_snapshot(
            positions=positions,
            cash=self.cash,
        )
