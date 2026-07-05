from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass
class Trade:
    """
    A complete lifecycle of a position.

    G19: entry → exit → realized PnL
    """

    trade_id: UUID
    symbol: str

    entry_price: Decimal
    exit_price: Decimal | None = None

    quantity: int = 0

    entry_time: datetime | None = None
    exit_time: datetime | None = None

    realized_pnl: Decimal = Decimal("0")

    is_open: bool = True
