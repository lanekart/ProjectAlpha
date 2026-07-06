from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from alpha.analysis.simulation.clock import SimulationClock
from alpha.analysis.simulation.event import SimulationEvent, SimulationEventType
from alpha.analysis.simulation.queue import EventQueue

EventHandler = Callable[[SimulationEvent], tuple[SimulationEvent, ...]]


@dataclass(slots=True)
class SimulationEngine:
    """
    Deterministic event-driven simulation engine.

    This engine is intentionally infrastructure-only. Domain handlers
    translate MARKET events into signals, orders, fills, snapshots, and
    analytics without embedding strategy/accounting logic here.
    """

    queue: EventQueue = field(default_factory=EventQueue)
    clock: SimulationClock = field(default_factory=SimulationClock)
    _handlers: dict[SimulationEventType, EventHandler] = field(default_factory=dict)

    def register_handler(
        self,
        event_type: SimulationEventType,
        handler: EventHandler,
    ) -> None:
        self._handlers[event_type] = handler

    def submit(self, event: SimulationEvent) -> None:
        self.queue.push(event)

    def run(self) -> tuple[SimulationEvent, ...]:
        processed: list[SimulationEvent] = []

        while self.queue:
            event = self.queue.pop()
            self.clock.advance_to(event.timestamp)
            processed.append(event)

            handler = self._handlers.get(event.event_type)

            if handler is None:
                continue

            for produced_event in handler(event):
                self.submit(produced_event)

        return tuple(processed)
