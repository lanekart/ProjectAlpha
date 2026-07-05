from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alpha.execution.fill import Fill
from alpha.portfolio.inventory import InventoryLot
from alpha.portfolio.inventory_book import InventoryBook
from alpha.portfolio.ledger_event import LedgerEvent
from alpha.portfolio.portfolio_ledger import PortfolioLedger
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot
from alpha.portfolio.position import Position
from alpha.portfolio.snapshot_book import SnapshotBook


@dataclass
class AccountingEngine:
    """
    Institutional portfolio accounting engine.

    Responsibilities
    ----------------
    - Maintain FIFO inventory
    - Update portfolio quantity
    - Maintain average remaining cost basis
    - Compute realized PnL
    - Record immutable ledger events
    - Produce immutable portfolio snapshots
    """

    inventory: InventoryBook = field(default_factory=InventoryBook)
    ledger: PortfolioLedger = field(default_factory=PortfolioLedger)
    snapshots: SnapshotBook = field(default_factory=SnapshotBook)

    def apply_fill(
        self,
        position: Position | None,
        fill: Fill,
    ) -> Position:
        """
        Apply a fill to a portfolio position.
        """

        # -------------------------------------------------
        # Create brand-new position
        # -------------------------------------------------

        if position is None:
            self.inventory.add_lot(
                InventoryLot(
                    fill_id=fill.fill_id,
                    quantity=fill.quantity,
                    price=fill.price,
                    timestamp=fill.timestamp,
                )
            )

            position = Position(
                position_id=uuid4(),
                symbol=str(fill.order_id),
                quantity=fill.quantity,
                average_price=fill.price,
                realized_pnl=Decimal("0"),
                entry_time=fill.timestamp,
            )

        # -------------------------------------------------
        # Existing position
        # -------------------------------------------------

        else:
            if fill.quantity > 0:
                self.inventory.add_lot(
                    InventoryLot(
                        fill_id=fill.fill_id,
                        quantity=fill.quantity,
                        price=fill.price,
                        timestamp=fill.timestamp,
                    )
                )

                position.quantity += fill.quantity

            else:
                realized = self.inventory.consume_fifo(
                    quantity=abs(fill.quantity),
                    exit_price=fill.price,
                )

                position.quantity += fill.quantity
                position.realized_pnl += realized

            remaining = self.inventory.open_lots()

            if remaining:
                total_quantity = sum(lot.quantity for lot in remaining)

                total_cost = sum(
                    (lot.price * Decimal(lot.quantity) for lot in remaining),
                    Decimal("0"),
                )

                position.average_price = total_cost / Decimal(total_quantity)
            else:
                position.average_price = Decimal("0")

        # -------------------------------------------------
        # Validate accounting state
        # -------------------------------------------------

        self._validate_state(position)

        # -------------------------------------------------
        # Record immutable accounting event
        # -------------------------------------------------

        self.ledger.append(
            LedgerEvent(
                event_id=uuid4(),
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                symbol=position.symbol,
                quantity=fill.quantity,
                price=fill.price,
                realized_pnl=position.realized_pnl,
                position_quantity=position.quantity,
                average_price=position.average_price,
                timestamp=fill.timestamp,
            )
        )

        return position

    def create_snapshot(
        self,
        position: Position,
    ) -> PortfolioSnapshot:
        """
        Capture an immutable portfolio snapshot.
        """

        snapshot = PortfolioSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(UTC),
            position_quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
        )

        self.snapshots.append(snapshot)

        return snapshot

    def _validate_state(
        self,
        position: Position,
    ) -> None:
        """
        Validate internal accounting invariants.
        """

        open_lots = self.inventory.open_lots()

        inventory_quantity = sum(lot.quantity for lot in open_lots)

        if inventory_quantity != position.quantity:
            raise ValueError("Inventory quantity does not match position quantity.")

        if position.average_price < Decimal("0"):
            raise ValueError("Average price cannot be negative.")

        if position.quantity == 0 and open_lots:
            raise ValueError("Flat position cannot have remaining inventory.")
