from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SimulationClock:
    """
    Monotonic simulation clock.
    """

    current_time: datetime | None = None

    def advance_to(self, timestamp: datetime) -> None:
        if timestamp.tzinfo is None:
            raise ValueError("SimulationClock timestamp must be timezone-aware")

        if self.current_time is not None and timestamp < self.current_time:
            raise ValueError("SimulationClock cannot move backwards")

        self.current_time = timestamp
