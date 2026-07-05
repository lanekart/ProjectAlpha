from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_EXIT = "TIME_EXIT"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class ExitSignal:
    """
    Represents a decision to exit a position.
    """

    position_id: UUID
    symbol: str
    quantity: int
    reason: ExitReason
