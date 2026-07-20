from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from alpha.decision_lifecycle import LifecycleState
from alpha.decision_orchestrator import (
    AdvisorAuthority,
    AdvisorSignal,
    DecisionContext,
    DecisionOrchestrator,
    OrchestratedDecision,
)


class CommitteeMandate(StrEnum):
    TECHNICAL = "TECHNICAL"
    FUNDAMENTAL = "FUNDAMENTAL"
    RISK = "RISK"
    MARKET = "MARKET"
    PORTFOLIO = "PORTFOLIO"
    EXECUTION = "EXECUTION"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class CommitteeMember:
    member_id: str
    display_name: str
    mandate: CommitteeMandate
    authority: AdvisorAuthority
    description: str
    active: bool = True

    def __post_init__(self) -> None:
        member_id = self.member_id.strip().upper()
        display_name = self.display_name.strip()
        description = self.description.strip()
        if not member_id:
            raise ValueError("committee member_id cannot be empty")
        if not display_name:
            raise ValueError("committee display_name cannot be empty")
        if not description:
            raise ValueError("committee description cannot be empty")
        object.__setattr__(self, "member_id", member_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "mandate", CommitteeMandate(self.mandate))
        object.__setattr__(self, "authority", AdvisorAuthority(self.authority))
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class CommitteeVote:
    member: CommitteeMember
    proposed_state: LifecycleState
    confidence: Decimal
    reason: str
    evidence_ids: tuple[str, ...]
    veto: bool = False

    def __post_init__(self) -> None:
        confidence = Decimal(self.confidence)
        reason = self.reason.strip()
        evidence_ids = tuple(
            sorted({item.strip().upper() for item in self.evidence_ids if item.strip()})
        )
        if not self.member.active:
            raise ValueError("inactive committee member cannot vote")
        if not Decimal("0") < confidence <= Decimal("1"):
            raise ValueError(
                "committee confidence must be greater than 0 and at most 1"
            )
        if not reason:
            raise ValueError("committee vote reason cannot be empty")
        if not evidence_ids:
            raise ValueError("committee vote requires evidence ids")
        object.__setattr__(self, "proposed_state", LifecycleState(self.proposed_state))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_signal(self) -> AdvisorSignal:
        return AdvisorSignal(
            source=self.member.member_id,
            proposed_state=self.proposed_state,
            authority=self.member.authority,
            confidence=self.confidence,
            reason=self.reason,
            evidence_ids=self.evidence_ids,
            veto=self.veto,
        )


@dataclass(frozen=True, slots=True)
class CommitteeResult:
    decision: OrchestratedDecision
    votes: tuple[CommitteeVote, ...]
    vote_counts: tuple[tuple[LifecycleState, int], ...]
    consensus_score: int
    unanimous: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.consensus_score <= 100:
            raise ValueError("consensus_score must be between 0 and 100")
        if not self.votes:
            raise ValueError("committee result requires votes")
        if self.production_influence:
            raise ValueError("committee result cannot execute production orders")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.to_dict(),
            "votes": [
                {
                    "member_id": vote.member.member_id,
                    "display_name": vote.member.display_name,
                    "mandate": vote.member.mandate.value,
                    "proposed_state": vote.proposed_state.value,
                    "confidence": str(vote.confidence),
                    "reason": vote.reason,
                    "evidence_ids": list(vote.evidence_ids),
                    "veto": vote.veto,
                }
                for vote in self.votes
            ],
            "vote_counts": [
                {"state": state.value, "count": count}
                for state, count in self.vote_counts
            ],
            "consensus_score": self.consensus_score,
            "unanimous": self.unanimous,
            "production_influence": self.production_influence,
        }


class InvestmentCommittee:
    """Resolve independent governed committee votes through one chair."""

    def __init__(self, orchestrator: DecisionOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or DecisionOrchestrator()

    def convene(
        self,
        *,
        recommendation_id: str,
        symbol: str,
        context: DecisionContext,
        votes: tuple[CommitteeVote, ...],
        stability_score: int | None = None,
    ) -> CommitteeResult:
        if not votes:
            raise ValueError("investment committee requires at least one vote")
        member_ids = [vote.member.member_id for vote in votes]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("committee member ids must be unique")

        decision = self.orchestrator.decide(
            recommendation_id=recommendation_id,
            symbol=symbol,
            context=context,
            signals=tuple(vote.to_signal() for vote in votes),
            stability_score=stability_score,
        )
        counter = Counter(vote.proposed_state for vote in votes)
        vote_counts = tuple(
            (state, counter[state])
            for state in LifecycleState
            if counter[state] > 0
        )
        winning_votes = counter[decision.final_state]
        consensus = int(
            (
                (Decimal(winning_votes) / Decimal(len(votes))) * Decimal("100")
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        return CommitteeResult(
            decision=decision,
            votes=tuple(sorted(votes, key=lambda vote: vote.member.member_id)),
            vote_counts=vote_counts,
            consensus_score=consensus,
            unanimous=winning_votes == len(votes),
        )


def render_committee_minutes(result: CommitteeResult) -> tuple[str, ...]:
    lines = [
        "Alpha Investment Committee Minutes",
        f"Symbol: {result.decision.symbol}",
        f"Final Decision: {result.decision.final_state.value}",
        f"Chair Confidence: {result.decision.confidence_score}/100",
        f"Committee Consensus: {result.consensus_score}/100",
    ]
    if result.decision.stability_score is not None:
        lines.append(f"Decision Stability: {result.decision.stability_score}/100")
    lines.append("Committee Votes:")
    for vote in result.votes:
        marker = (
            "SELECTED"
            if vote.member.member_id == result.decision.winning_source
            else ""
        )
        suffix = f" [{marker}]" if marker else ""
        lines.append(
            f"- {vote.member.display_name}: {vote.proposed_state.value} "
            f"({vote.confidence}){suffix}"
        )
        lines.append(f"  Why: {vote.reason}")
    if result.decision.dissenting_sources:
        lines.append(
            "Dissenting Members: " + ", ".join(result.decision.dissenting_sources)
        )
    lines.append("Execution Status: NON-EXECUTABLE COMMITTEE DECISION")
    return tuple(lines)


def export_committee_json(result: CommitteeResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)
