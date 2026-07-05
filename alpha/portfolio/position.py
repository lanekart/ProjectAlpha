from dataclasses import dataclass
from datetime import date

from alpha.portfolio.enums import (
    Direction,
    ExitReason,
    PositionStatus,
)


@dataclass
class Position:
    symbol: str

    direction: Direction

    quantity: float

    entry_date: date

    entry_price: float

    stop_loss: float

    target: float

    status: PositionStatus = PositionStatus.OPEN

    exit_date: date | None = None

    exit_price: float | None = None

    exit_reason: ExitReason = ExitReason.UNKNOWN

    highest_price: float = 0.0

    lowest_price: float = 0.0

    realized_pnl: float = 0.0

    holding_days: int = 0
