from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum


class LifecycleState(StrEnum):
    WATCHLIST = "WATCHLIST"
    READY = "READY"
    BUY = "BUY"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    AVOID = "AVOID"
    EXPIRED = "EXPIRED"


class LifecycleConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LifecycleTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.WATCHLIST: frozenset(
        {LifecycleState.READY, LifecycleState.AVOID, LifecycleState.EXPIRED}
    ),
    LifecycleState.READY: frozenset(
        {
            LifecycleState.BUY,
            LifecycleState.WATCHLIST,
            LifecycleState.AVOID,
            LifecycleState.EXPIRED,
        }
    ),
    LifecycleState.BUY: frozenset({LifecycleState.HOLD, LifecycleState.EXIT}),
    LifecycleState.HOLD: frozenset(
        {LifecycleState.HOLD, LifecycleState.REDUCE, LifecycleState.EXIT}
    ),
    LifecycleState.REDUCE: frozenset(
        {LifecycleState.HOLD, LifecycleState.REDUCE, LifecycleState.EXIT}
    ),
    LifecycleState.EXIT: frozenset(),
    LifecycleState.AVOID: frozenset({LifecycleState.WATCHLIST, LifecycleState.EXPIRED}),
    LifecycleState.EXPIRED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class LifecycleEvidence:
    code: str
    detail: str

    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        detail = self.detail.strip()
        if not code:
            raise ValueError("evidence code cannot be empty")
        if not detail:
            raise ValueError("evidence detail cannot be empty")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "detail", detail)


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    recommendation_id: str
    symbol: str
    occurred_at: datetime
    previous_state: LifecycleState
    new_state: LifecycleState
    reason: str
    evidence: tuple[LifecycleEvidence, ...]
    confidence: LifecycleConfidence
    reduction_percent: int | None = None
    production_influence: bool = False

    def __post_init__(self) -> None:
        recommendation_id = self.recommendation_id.strip()
        symbol = self.symbol.strip().upper()
        reason = self.reason.strip()
        if not recommendation_id:
            raise ValueError("recommendation_id cannot be empty")
        if not symbol:
            raise ValueError("symbol cannot be empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not reason:
            raise ValueError("transition reason cannot be empty")
        if self.production_influence:
            raise ValueError("decision lifecycle cannot influence production execution")
        previous_state = LifecycleState(self.previous_state)
        new_state = LifecycleState(self.new_state)
        confidence = LifecycleConfidence(self.confidence)
        evidence = tuple(self.evidence)
        if not evidence:
            raise ValueError("transition requires supporting evidence")
        if new_state is LifecycleState.REDUCE:
            if self.reduction_percent is None or not 1 <= self.reduction_percent <= 100:
                raise ValueError("REDUCE requires reduction_percent between 1 and 100")
        elif self.reduction_percent is not None:
            raise ValueError("reduction_percent is valid only for REDUCE")
        object.__setattr__(self, "recommendation_id", recommendation_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "previous_state", previous_state)
        object.__setattr__(self, "new_state", new_state)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence", evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "symbol": self.symbol,
            "occurred_at": self.occurred_at.isoformat(),
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "reason": self.reason,
            "evidence": [asdict(item) for item in self.evidence],
            "confidence": self.confidence.value,
            "reduction_percent": self.reduction_percent,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    recommendation_id: str
    symbol: str
    current_state: LifecycleState
    history: tuple[LifecycleTransition, ...]


class LifecycleHistoryRepository:
    """Append-only in-memory transition repository.

    Persistence adapters may wrap this contract, but existing events are never
    updated or deleted.
    """

    def __init__(self) -> None:
        self._events: list[LifecycleTransition] = []

    def append(self, transition: LifecycleTransition) -> None:
        if transition in self._events:
            return
        related = self.history(transition.recommendation_id)
        if related:
            last = related[-1]
            if transition.occurred_at <= last.occurred_at:
                raise LifecycleTransitionError("transition timestamps must increase")
            if transition.previous_state is not last.new_state:
                raise LifecycleTransitionError(
                    "previous_state does not match current state"
                )
        self._events.append(transition)

    def history(self, recommendation_id: str) -> tuple[LifecycleTransition, ...]:
        return tuple(
            event
            for event in self._events
            if event.recommendation_id == recommendation_id
        )

    def all(self) -> tuple[LifecycleTransition, ...]:
        return tuple(self._events)


class DecisionLifecycleEngine:
    def __init__(self, repository: LifecycleHistoryRepository | None = None) -> None:
        self.repository = repository or LifecycleHistoryRepository()

    def transition(
        self,
        *,
        recommendation_id: str,
        symbol: str,
        occurred_at: datetime,
        previous_state: LifecycleState,
        new_state: LifecycleState,
        reason: str,
        evidence: Iterable[LifecycleEvidence],
        confidence: LifecycleConfidence,
        reduction_percent: int | None = None,
    ) -> LifecycleTransition:
        previous_state = LifecycleState(previous_state)
        new_state = LifecycleState(new_state)
        if new_state not in _ALLOWED_TRANSITIONS[previous_state]:
            raise LifecycleTransitionError(
                "illegal lifecycle transition: "
                f"{previous_state.value} -> {new_state.value}"
            )
        transition = LifecycleTransition(
            recommendation_id=recommendation_id,
            symbol=symbol,
            occurred_at=occurred_at,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            evidence=tuple(evidence),
            confidence=confidence,
            reduction_percent=reduction_percent,
        )
        self.repository.append(transition)
        return transition

    def record(self, recommendation_id: str) -> LifecycleRecord:
        history = self.repository.history(recommendation_id)
        if not history:
            raise KeyError(recommendation_id)
        latest = history[-1]
        return LifecycleRecord(
            recommendation_id=recommendation_id,
            symbol=latest.symbol,
            current_state=latest.new_state,
            history=history,
        )


def explain_transition(transition: LifecycleTransition) -> tuple[str, ...]:
    lines = [
        f"{transition.previous_state.value} -> {transition.new_state.value}",
        f"Reason: {transition.reason}",
        f"Confidence: {transition.confidence.value}",
        "Supporting Evidence:",
    ]
    lines.extend(f"- {item.code}: {item.detail}" for item in transition.evidence)
    if transition.reduction_percent is not None:
        lines.append(f"Suggested Reduction: {transition.reduction_percent}%")
    lines.append("Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE")
    return tuple(lines)


def render_timeline(record: LifecycleRecord) -> tuple[str, ...]:
    lines = [f"Decision Lifecycle Timeline: {record.symbol}"]
    for index, transition in enumerate(record.history):
        if index == 0:
            lines.append(transition.previous_state.value)
        lines.extend(
            (
                "↓",
                f"{transition.new_state.value} — {transition.occurred_at.isoformat()}",
            )
        )
    return tuple(lines)


def export_history_json(events: Iterable[LifecycleTransition]) -> str:
    return json.dumps(
        [event.to_dict() for event in events],
        indent=2,
        sort_keys=True,
    )
