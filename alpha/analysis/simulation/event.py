from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class SimulationEventType(StrEnum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    SNAPSHOT = "SNAPSHOT"


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    """
    Immutable event flowing through the deterministic simulation engine.
    """

    timestamp: datetime
    event_type: SimulationEventType
    payload: Any
    event_id: UUID = uuid4()

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("SimulationEvent timestamp must be timezone-aware")
