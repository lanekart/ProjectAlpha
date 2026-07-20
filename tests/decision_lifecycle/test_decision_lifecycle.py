from datetime import UTC, datetime, timedelta

import pytest

from alpha.decision_lifecycle import (
    DecisionLifecycleEngine,
    LifecycleConfidence,
    LifecycleEvidence,
    LifecycleHistoryRepository,
    LifecycleState,
    LifecycleTransitionError,
    explain_transition,
    export_history_json,
    render_timeline,
)


def evidence(code: str = "ENTRY") -> tuple[LifecycleEvidence, ...]:
    return (LifecycleEvidence(code, "Point-in-time evidence remains supportive."),)


def test_watchlist_can_promote_to_ready() -> None:
    engine = DecisionLifecycleEngine()
    event = engine.transition(
        recommendation_id="rec-1",
        symbol="tatva",
        occurred_at=datetime(2026, 7, 20, 9, 15, tzinfo=UTC),
        previous_state=LifecycleState.WATCHLIST,
        new_state=LifecycleState.READY,
        reason="Preferred entry zone reached with bullish structure intact.",
        evidence=evidence(),
        confidence=LifecycleConfidence.HIGH,
    )
    assert event.symbol == "TATVA"
    assert engine.record("rec-1").current_state is LifecycleState.READY


def test_full_governed_lifecycle_is_append_only() -> None:
    repository = LifecycleHistoryRepository()
    engine = DecisionLifecycleEngine(repository)
    base = datetime(2026, 7, 20, 9, 15, tzinfo=UTC)
    transitions = (
        (LifecycleState.WATCHLIST, LifecycleState.READY, None),
        (LifecycleState.READY, LifecycleState.BUY, None),
        (LifecycleState.BUY, LifecycleState.HOLD, None),
        (LifecycleState.HOLD, LifecycleState.REDUCE, 25),
        (LifecycleState.REDUCE, LifecycleState.EXIT, None),
    )
    for index, (previous, new, reduction) in enumerate(transitions):
        engine.transition(
            recommendation_id="rec-2",
            symbol="IDFCFIRSTB",
            occurred_at=base + timedelta(days=index),
            previous_state=previous,
            new_state=new,
            reason=f"Governed transition to {new.value}.",
            evidence=evidence(new.value),
            confidence=LifecycleConfidence.MEDIUM,
            reduction_percent=reduction,
        )
    history = repository.history("rec-2")
    assert len(history) == 5
    assert history[0].previous_state is LifecycleState.WATCHLIST
    assert history[-1].new_state is LifecycleState.EXIT
    assert isinstance(repository.all(), tuple)


def test_illegal_transition_fails_closed() -> None:
    engine = DecisionLifecycleEngine()
    with pytest.raises(LifecycleTransitionError, match="WATCHLIST -> HOLD"):
        engine.transition(
            recommendation_id="rec-3",
            symbol="ABC",
            occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
            previous_state=LifecycleState.WATCHLIST,
            new_state=LifecycleState.HOLD,
            reason="Invalid shortcut.",
            evidence=evidence(),
            confidence=LifecycleConfidence.LOW,
        )


def test_repository_rejects_history_rewrite() -> None:
    engine = DecisionLifecycleEngine()
    now = datetime(2026, 7, 20, tzinfo=UTC)
    engine.transition(
        recommendation_id="rec-4",
        symbol="ABC",
        occurred_at=now,
        previous_state=LifecycleState.WATCHLIST,
        new_state=LifecycleState.READY,
        reason="Ready.",
        evidence=evidence(),
        confidence=LifecycleConfidence.HIGH,
    )
    with pytest.raises(LifecycleTransitionError, match="previous_state"):
        engine.transition(
            recommendation_id="rec-4",
            symbol="ABC",
            occurred_at=now + timedelta(days=1),
            previous_state=LifecycleState.WATCHLIST,
            new_state=LifecycleState.EXPIRED,
            reason="Attempted rewrite.",
            evidence=evidence(),
            confidence=LifecycleConfidence.HIGH,
        )


def test_reduce_requires_explicit_percentage() -> None:
    engine = DecisionLifecycleEngine()
    with pytest.raises(ValueError, match="REDUCE requires"):
        engine.transition(
            recommendation_id="rec-5",
            symbol="ABC",
            occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
            previous_state=LifecycleState.HOLD,
            new_state=LifecycleState.REDUCE,
            reason="Concentration risk increased.",
            evidence=evidence("CONCENTRATION"),
            confidence=LifecycleConfidence.MEDIUM,
        )


def test_explanation_timeline_and_json_are_deterministic() -> None:
    engine = DecisionLifecycleEngine()
    event = engine.transition(
        recommendation_id="rec-6",
        symbol="ABC",
        occurred_at=datetime(2026, 7, 20, 9, 15, tzinfo=UTC),
        previous_state=LifecycleState.WATCHLIST,
        new_state=LifecycleState.READY,
        reason="Risk/reward improved.",
        evidence=evidence("RISK_REWARD"),
        confidence=LifecycleConfidence.HIGH,
    )
    explanation = explain_transition(event)
    timeline = render_timeline(engine.record("rec-6"))
    exported = export_history_json(engine.repository.all())
    assert explanation[-1] == "Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE"
    assert timeline[:3] == (
        "Decision Lifecycle Timeline: ABC",
        "WATCHLIST",
        "↓",
    )
    assert '"production_influence": false' in exported
    assert '"new_state": "READY"' in exported
