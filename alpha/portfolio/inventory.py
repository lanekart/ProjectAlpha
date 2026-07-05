from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True)
class InventoryLot:
    """
    Represents a single acquisition lot.

    Every executed BUY creates one lot.

    Later SELL fills consume these lots using FIFO.
    """

    fill_id: UUID

    quantity: int

    price: Decimal

    timestamp: datetime

    @property
    def is_empty(self) -> bool:
        return self.quantity == 0
