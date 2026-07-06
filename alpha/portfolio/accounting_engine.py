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
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot
from alpha.portfolio.position import Position
from alpha.portfolio.snapshot_book import SnapshotBook


@dataclass
class AccountingEngine:
    """
    Institutional portfolio accounting engine.
    """

    inventory: InventoryBook = field(default_factory=InventoryBook)
    ledger: PortfolioLedger = field(default_factory=PortfolioLedger)
    snapshots: SnapshotBook = field(default_factory=SnapshotBook)

    def apply_fill(
        self,
        position: Position | None,
        fill: Fill,
    ) -> Position:
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
                symbol=fill.symbol,
                quantity=fill.quantity,
                average_price=fill.price,
                realized_pnl=Decimal("0"),
                entry_time=fill.timestamp,
                commission=fill.commission,
                slippage=fill.slippage,
            )
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

            position.commission += fill.commission
            position.slippage += fill.slippage

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

        self._validate_state(position)

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
        positions: tuple[Position, ...],
        cash: Decimal = Decimal("0"),
    ) -> PortfolioSnapshot:
        snapshot = PortfolioSnapshot(
            snapshot_id=uuid4(),
            timestamp=datetime.now(UTC),
            cash=cash,
            positions=tuple(
                PositionSnapshot(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    average_price=position.average_price,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position.unrealized_pnl,
                    commission=position.commission,
                    slippage=position.slippage,
                )
                for position in positions
            ),
        )

        self.snapshots.append(snapshot)

        return snapshot

    def _validate_state(
        self,
        position: Position,
    ) -> None:
        open_lots = self.inventory.open_lots()

        inventory_quantity = sum(lot.quantity for lot in open_lots)

        if inventory_quantity != position.quantity:
            raise ValueError("Inventory quantity does not match position quantity.")

        if position.average_price < Decimal("0"):
            raise ValueError("Average price cannot be negative.")

        if position.quantity == 0 and open_lots:
            raise ValueError("Flat position cannot have remaining inventory.")
