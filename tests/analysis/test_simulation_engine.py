from datetime import UTC, datetime, timedelta

import pytest

from alpha.analysis.simulation.clock import SimulationClock
from alpha.analysis.simulation.engine import SimulationEngine
from alpha.analysis.simulation.event import SimulationEvent, SimulationEventType
from alpha.analysis.simulation.queue import EventQueue


def make_event(
    timestamp: datetime,
    event_type: SimulationEventType = SimulationEventType.MARKET,
    payload: object = "payload",
) -> SimulationEvent:
    return SimulationEvent(
        timestamp=timestamp,
        event_type=event_type,
        payload=payload,
    )


def test_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        make_event(datetime.now())


def test_event_queue_orders_by_timestamp() -> None:
    start = datetime.now(UTC)

    queue = EventQueue()
    later = make_event(start + timedelta(days=1), payload="later")
    earlier = make_event(start, payload="earlier")

    queue.push(later)
    queue.push(earlier)

    assert queue.pop().payload == "earlier"
    assert queue.pop().payload == "later"


def test_event_queue_drain() -> None:
    start = datetime.now(UTC)

    queue = EventQueue()
    queue.push(make_event(start, payload="first"))
    queue.push(make_event(start + timedelta(days=1), payload="second"))

    drained = queue.drain()

    assert len(drained) == 2
    assert len(queue) == 0
    assert drained[0].payload == "first"
    assert drained[1].payload == "second"


def test_clock_rejects_backwards_time() -> None:
    start = datetime.now(UTC)

    clock = SimulationClock()
    clock.advance_to(start)

    with pytest.raises(ValueError):
        clock.advance_to(start - timedelta(seconds=1))


def test_simulation_engine_processes_events_in_order() -> None:
    start = datetime.now(UTC)

    engine = SimulationEngine()
    engine.submit(make_event(start + timedelta(days=1), payload="second"))
    engine.submit(make_event(start, payload="first"))

    processed = engine.run()

    assert tuple(event.payload for event in processed) == ("first", "second")
    assert engine.clock.current_time == start + timedelta(days=1)


def test_simulation_engine_handler_can_emit_new_events() -> None:
    start = datetime.now(UTC)

    engine = SimulationEngine()

    def handle_market(event: SimulationEvent) -> tuple[SimulationEvent, ...]:
        return (
            SimulationEvent(
                timestamp=event.timestamp + timedelta(seconds=1),
                event_type=SimulationEventType.SIGNAL,
                payload="signal",
            ),
        )

    engine.register_handler(SimulationEventType.MARKET, handle_market)
    engine.submit(make_event(start, SimulationEventType.MARKET, "market"))

    processed = engine.run()

    assert tuple(event.event_type for event in processed) == (
        SimulationEventType.MARKET,
        SimulationEventType.SIGNAL,
    )
    assert tuple(event.payload for event in processed) == ("market", "signal")
