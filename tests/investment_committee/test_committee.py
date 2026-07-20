from __future__ import annotations

import json
from decimal import Decimal

import pytest

from alpha.decision_lifecycle import LifecycleState
from alpha.decision_orchestrator import AdvisorAuthority, DecisionContext
from alpha.investment_committee import (
    CommitteeMandate,
    CommitteeMember,
    CommitteeVote,
    InvestmentCommittee,
    export_committee_json,
    render_committee_minutes,
)


def _member(
    member_id: str,
    mandate: CommitteeMandate,
    authority: AdvisorAuthority = AdvisorAuthority.PRIMARY,
) -> CommitteeMember:
    return CommitteeMember(
        member_id=member_id,
        display_name=member_id.replace("_", " ").title(),
        mandate=mandate,
        authority=authority,
        description=f"Mandate for {member_id}",
    )


def _vote(
    member: CommitteeMember,
    state: LifecycleState,
    *,
    confidence: str = "0.8",
    veto: bool = False,
) -> CommitteeVote:
    return CommitteeVote(
        member=member,
        proposed_state=state,
        confidence=Decimal(confidence),
        reason=f"{member.display_name} recommends {state.value}",
        evidence_ids=(f"{member.member_id}_EVIDENCE",),
        veto=veto,
    )


def test_committee_reports_vote_consensus() -> None:
    technical = _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL)
    fundamental = _member("FUNDAMENTAL_CIO", CommitteeMandate.FUNDAMENTAL)
    market = _member("MARKET_STRATEGIST", CommitteeMandate.MARKET)
    result = InvestmentCommittee().convene(
        recommendation_id="rec-1",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        votes=(
            _vote(technical, LifecycleState.READY),
            _vote(fundamental, LifecycleState.READY),
            _vote(market, LifecycleState.WATCHLIST),
        ),
    )

    assert result.decision.final_state is LifecycleState.READY
    assert result.consensus_score == 67
    assert result.unanimous is False


def test_risk_veto_overrides_majority() -> None:
    technical = _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL)
    fundamental = _member("FUNDAMENTAL_CIO", CommitteeMandate.FUNDAMENTAL)
    risk = _member(
        "RISK_OFFICER",
        CommitteeMandate.RISK,
        authority=AdvisorAuthority.HARD_RISK,
    )
    result = InvestmentCommittee().convene(
        recommendation_id="rec-2",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        votes=(
            _vote(technical, LifecycleState.READY),
            _vote(fundamental, LifecycleState.READY),
            _vote(risk, LifecycleState.AVOID, veto=True),
        ),
    )

    assert result.decision.final_state is LifecycleState.AVOID
    assert result.decision.winning_source == "RISK_OFFICER"
    assert result.consensus_score == 33


def test_unanimous_committee_is_reported() -> None:
    members = (
        _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL),
        _member("MARKET_STRATEGIST", CommitteeMandate.MARKET),
    )
    result = InvestmentCommittee().convene(
        recommendation_id="rec-3",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        votes=tuple(_vote(member, LifecycleState.WATCHLIST) for member in members),
    )

    assert result.consensus_score == 100
    assert result.unanimous is True


def test_duplicate_committee_member_fails_closed() -> None:
    member = _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL)
    with pytest.raises(ValueError, match="member ids must be unique"):
        InvestmentCommittee().convene(
            recommendation_id="rec-4",
            symbol="abc",
            context=DecisionContext.CANDIDATE,
            votes=(
                _vote(member, LifecycleState.READY),
                _vote(member, LifecycleState.WATCHLIST),
            ),
        )


def test_inactive_member_cannot_vote() -> None:
    member = CommitteeMember(
        member_id="RETIRED_MEMBER",
        display_name="Retired Member",
        mandate=CommitteeMandate.OTHER,
        authority=AdvisorAuthority.CONTEXT,
        description="Inactive member",
        active=False,
    )
    with pytest.raises(ValueError, match="inactive"):
        _vote(member, LifecycleState.WATCHLIST)


def test_minutes_include_reasons_and_dissent() -> None:
    technical = _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL)
    market = _member("MARKET_STRATEGIST", CommitteeMandate.MARKET)
    result = InvestmentCommittee().convene(
        recommendation_id="rec-5",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        votes=(
            _vote(technical, LifecycleState.READY),
            _vote(market, LifecycleState.WATCHLIST),
        ),
        stability_score=75,
    )
    lines = render_committee_minutes(result)

    assert "Committee Consensus: 50/100" in lines
    assert "Decision Stability: 75/100" in lines
    assert any(line.startswith("  Why:") for line in lines)
    assert "Dissenting Members: MARKET_STRATEGIST" in lines


def test_json_export_is_deterministic() -> None:
    technical = _member("TECHNICAL_CIO", CommitteeMandate.TECHNICAL)
    result = InvestmentCommittee().convene(
        recommendation_id="rec-6",
        symbol="abc",
        context=DecisionContext.CANDIDATE,
        votes=(_vote(technical, LifecycleState.READY),),
    )
    payload = json.loads(export_committee_json(result))

    assert payload["decision"]["final_state"] == "READY"
    assert payload["consensus_score"] == 100
    assert payload["votes"][0]["mandate"] == "TECHNICAL"
    assert payload["production_influence"] is False


def test_empty_committee_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one vote"):
        InvestmentCommittee().convene(
            recommendation_id="rec-7",
            symbol="abc",
            context=DecisionContext.CANDIDATE,
            votes=(),
        )
