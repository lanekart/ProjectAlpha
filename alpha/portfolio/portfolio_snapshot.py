from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """
    Immutable checkpoint of portfolio state.

    Snapshots accelerate reconstruction by allowing replay
    from the latest checkpoint instead of replaying the
    entire ledger history.
    """

    snapshot_id: UUID

    timestamp: datetime

    position_quantity: int

    average_price: Decimal

    realized_pnl: Decimal
