from __future__ import annotations

from dataclasses import dataclass, field

from alpha.analysis.simulation.event import SimulationEvent


@dataclass(slots=True)
class EventQueue:
    """
    Deterministic FIFO event queue ordered by timestamp.
    """

    _events: list[SimulationEvent] = field(default_factory=list)

    def push(self, event: SimulationEvent) -> None:
        self._events.append(event)
        self._events.sort(key=lambda item: item.timestamp)

    def pop(self) -> SimulationEvent:
        if not self._events:
            raise IndexError("Cannot pop from an empty EventQueue")

        return self._events.pop(0)

    def peek(self) -> SimulationEvent | None:
        if not self._events:
            return None

        return self._events[0]

    def drain(self) -> tuple[SimulationEvent, ...]:
        events: list[SimulationEvent] = []

        while self._events:
            events.append(self.pop())

        return tuple(events)

    def clear(self) -> None:
        self._events.clear()

    def __len__(self) -> int:
        return len(self._events)

    def __bool__(self) -> bool:
        return bool(self._events)
