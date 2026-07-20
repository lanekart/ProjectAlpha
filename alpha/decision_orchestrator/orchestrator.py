from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import IntEnum, StrEnum

from alpha.decision_lifecycle import LifecycleState


class DecisionContext(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE_POSITION = "ACTIVE_POSITION"
    EXECUTION = "EXECUTION"


class AdvisorAuthority(IntEnum):
    CONTEXT = 10
    PRIMARY = 20
    GOVERNANCE = 30
    HARD_RISK = 40
    EXECUTION_CONFIRMATION = 50


_ALLOWED_STATES: dict[DecisionContext, frozenset[LifecycleState]] = {
    DecisionContext.CANDIDATE: frozenset(
        {
            LifecycleState.WATCHLIST,
            LifecycleState.READY,
            LifecycleState.AVOID,
            LifecycleState.EXPIRED,
        }
    ),
    DecisionContext.ACTIVE_POSITION: frozenset(
        {
            LifecycleState.HOLD,
            LifecycleState.REDUCE,
            LifecycleState.EXIT,
        }
    ),
    DecisionContext.EXECUTION: frozenset({LifecycleState.BUY}),
}

_STATE_PRECEDENCE: dict[DecisionContext, dict[LifecycleState, int]] = {
    DecisionContext.CANDIDATE: {
        LifecycleState.AVOID: 40,
        LifecycleState.EXPIRED: 30,
        LifecycleState.READY: 20,
        LifecycleState.WATCHLIST: 10,
    },
    DecisionContext.ACTIVE_POSITION: {
        LifecycleState.EXIT: 30,
        LifecycleState.REDUCE: 20,
        LifecycleState.HOLD: 10,
    },
    DecisionContext.EXECUTION: {LifecycleState.BUY: 10},
}

_URGENCY: dict[LifecycleState, int] = {
    LifecycleState.EXIT: 100,
    LifecycleState.AVOID: 90,
    LifecycleState.REDUCE: 80,
    LifecycleState.EXPIRED: 70,
    LifecycleState.BUY: 65,
    LifecycleState.READY: 55,
    LifecycleState.HOLD: 30,
    LifecycleState.WATCHLIST: 20,
}


@dataclass(frozen=True, slots=True)
class AdvisorSignal:
    source: str
    proposed_state: LifecycleState
    authority: AdvisorAuthority
    confidence: Decimal
    reason: str
    evidence_ids: tuple[str, ...]
    veto: bool = False

    def __post_init__(self) -> None:
        source = self.source.strip().upper()
        reason = self.reason.strip()
        confidence = Decimal(self.confidence)
        evidence_ids = tuple(
            sorted({item.strip().upper() for item in self.evidence_ids if item.strip()})
        )
        if not source:
            raise ValueError("advisor source cannot be empty")
        if not reason:
            raise ValueError("advisor reason cannot be empty")
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError("advisor confidence must be between 0 and 1")
        if not evidence_ids:
            raise ValueError("advisor signal requires evidence ids")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "proposed_state",
            LifecycleState(self.proposed_state),
        )
        object.__setattr__(self, "authority", AdvisorAuthority(self.authority))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class DecisionTraceStep:
    source: str
    proposed_state: LifecycleState
    authority: AdvisorAuthority
    confidence: Decimal
    veto: bool
    selected: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "proposed_state": self.proposed_state.value,
            "authority": self.authority.name,
            "confidence": str(self.confidence),
            "veto": self.veto,
            "selected": self.selected,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OrchestratedDecision:
    recommendation_id: str
    symbol: str
    context: DecisionContext
    final_state: LifecycleState
    confidence_score: int
    urgency_score: int
    winning_source: str
    supporting_sources: tuple[str, ...]
    dissenting_sources: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    stability_score: int | None
    trace: tuple[DecisionTraceStep, ...]
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.confidence_score <= 100:
            raise ValueError("confidence_score must be between 0 and 100")
        if not 0 <= self.urgency_score <= 100:
            raise ValueError("urgency_score must be between 0 and 100")
        if self.stability_score is not None and not 0 <= self.stability_score <= 100:
            raise ValueError("stability_score must be between 0 and 100")
        if self.production_influence:
            raise ValueError("orchestrated decision cannot execute production orders")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["context"] = self.context.value
        payload["final_state"] = self.final_state.value
        payload["trace"] = [step.to_dict() for step in self.trace]
        return payload


class DecisionOrchestrator:
    """Resolve governed advisor signals into one lifecycle state."""

    def decide(
        self,
        *,
        recommendation_id: str,
        symbol: str,
        context: DecisionContext,
        signals: tuple[AdvisorSignal, ...],
        stability_score: int | None = None,
    ) -> OrchestratedDecision:
        recommendation_id = recommendation_id.strip()
        symbol = symbol.strip().upper()
        context = DecisionContext(context)
        if not recommendation_id:
            raise ValueError("recommendation_id cannot be empty")
        if not symbol:
            raise ValueError("symbol cannot be empty")
        if not signals:
            raise ValueError("orchestrator requires at least one advisor signal")

        sources = [signal.source for signal in signals]
        if len(sources) != len(set(sources)):
            raise ValueError("advisor sources must be unique")
        for signal in signals:
            if signal.proposed_state not in _ALLOWED_STATES[context]:
                raise ValueError(
                    f"{signal.proposed_state.value} is invalid for {context.value}"
                )
            if (
                context is DecisionContext.EXECUTION
                and signal.authority is not AdvisorAuthority.EXECUTION_CONFIRMATION
            ):
                raise ValueError(
                    "BUY requires explicit execution-confirmation authority"
                )

        eligible = tuple(signal for signal in signals if signal.veto) or signals
        winner = max(eligible, key=lambda signal: self._rank(context, signal))
        supporting = tuple(
            sorted(
                signal.source
                for signal in signals
                if signal.proposed_state is winner.proposed_state
            )
        )
        dissenting = tuple(
            sorted(
                signal.source
                for signal in signals
                if signal.proposed_state is not winner.proposed_state
            )
        )
        confidence_score = self._confidence_score(signals, winner)
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for signal in signals
                    if signal.proposed_state is winner.proposed_state
                    for evidence_id in signal.evidence_ids
                }
            )
        )
        trace = tuple(
            DecisionTraceStep(
                source=signal.source,
                proposed_state=signal.proposed_state,
                authority=signal.authority,
                confidence=signal.confidence,
                veto=signal.veto,
                selected=signal.source == winner.source,
                reason=signal.reason,
            )
            for signal in sorted(signals, key=lambda item: item.source)
        )
        return OrchestratedDecision(
            recommendation_id=recommendation_id,
            symbol=symbol,
            context=context,
            final_state=winner.proposed_state,
            confidence_score=confidence_score,
            urgency_score=_URGENCY[winner.proposed_state],
            winning_source=winner.source,
            supporting_sources=supporting,
            dissenting_sources=dissenting,
            evidence_ids=evidence_ids,
            stability_score=stability_score,
            trace=trace,
        )

    @staticmethod
    def _rank(
        context: DecisionContext,
        signal: AdvisorSignal,
    ) -> tuple[int, int, Decimal, str]:
        return (
            int(signal.authority),
            _STATE_PRECEDENCE[context][signal.proposed_state],
            signal.confidence,
            signal.source,
        )

    @staticmethod
    def _confidence_score(
        signals: tuple[AdvisorSignal, ...],
        winner: AdvisorSignal,
    ) -> int:
        authority_weight = {
            authority: Decimal(int(authority)) for authority in AdvisorAuthority
        }
        total_weight = sum(
            (
                signal.confidence * authority_weight[signal.authority]
                for signal in signals
            ),
            Decimal("0"),
        )
        if total_weight == 0:
            raise ValueError("at least one advisor must have positive confidence")
        supporting_weight = sum(
            (
                signal.confidence * authority_weight[signal.authority]
                for signal in signals
                if signal.proposed_state is winner.proposed_state
            ),
            Decimal("0"),
        )
        score = (supporting_weight / total_weight) * Decimal("100")
        return int(score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def render_orchestrated_decision(
    decision: OrchestratedDecision,
) -> tuple[str, ...]:
    lines = [
        "Alpha Authoritative Decision",
        f"Symbol: {decision.symbol}",
        f"Context: {decision.context.value}",
        f"Final State: {decision.final_state.value}",
        f"Confidence: {decision.confidence_score}/100",
        f"Urgency: {decision.urgency_score}/100",
        f"Winning Source: {decision.winning_source}",
        "Supporting Sources: " + ", ".join(decision.supporting_sources),
    ]
    if decision.dissenting_sources:
        lines.append("Dissenting Sources: " + ", ".join(decision.dissenting_sources))
    if decision.stability_score is not None:
        lines.append(f"Stability: {decision.stability_score}/100")
    lines.append("Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE")
    return tuple(lines)


def export_orchestrated_decision_json(decision: OrchestratedDecision) -> str:
    return json.dumps(decision.to_dict(), indent=2, sort_keys=True)
