from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from alpha.decision_intelligence.opportunity_pipeline import OpportunityPipelineAction
from alpha.decision_lifecycle import (
    DecisionLifecycleEngine,
    LifecycleConfidence,
    LifecycleEvidence,
    LifecycleState,
    OpportunityLifecycleAdapter,
    PositionReviewEngine,
    PositionReviewInput,
    build_lifecycle_summary,
    export_history_csv,
    render_lifecycle_summary,
)


def pipeline_decision(action: OpportunityPipelineAction) -> Any:
    candidate = SimpleNamespace(final_verdict="BUY")
    decision = SimpleNamespace(candidate=candidate)
    return cast(
        Any,
        SimpleNamespace(
            action=action,
            symbol="tatva",
            decision=decision,
            explanation="Bullish opportunity remains visible but is not executable.",
            watchlist_reasons=(),
        ),
    )


def test_pipeline_buy_maps_to_ready_not_executed_buy() -> None:
    seed = OpportunityLifecycleAdapter().seed(
        pipeline_decision(OpportunityPipelineAction.BUY),
        recommendation_id="rec-buy",
    )
    assert seed.state is LifecycleState.READY
    assert seed.symbol == "TATVA"
    assert seed.production_influence is False
    assert "human-confirmed" in seed.reason


def test_pipeline_watchlist_and_reject_map_conservatively() -> None:
    adapter = OpportunityLifecycleAdapter()
    watchlist = adapter.seed(
        pipeline_decision(OpportunityPipelineAction.WATCHLIST),
        recommendation_id="rec-watch",
    )
    rejected = adapter.seed(
        pipeline_decision(OpportunityPipelineAction.REJECT),
        recommendation_id="rec-reject",
    )
    assert watchlist.state is LifecycleState.WATCHLIST
    assert rejected.state is LifecycleState.AVOID


def test_position_review_exit_has_precedence_over_reduce() -> None:
    decision = PositionReviewEngine().review(
        PositionReviewInput(
            symbol="abc",
            stop_broken=True,
            target_achieved=True,
            weakening_trend=True,
        )
    )
    assert decision.state is LifecycleState.EXIT
    assert decision.confidence is LifecycleConfidence.HIGH
    assert decision.reduction_percent is None
    assert decision.evidence[0].code == "STOP_BROKEN"


def test_position_review_reduce_for_concentration_and_weakness() -> None:
    decision = PositionReviewEngine().review(
        PositionReviewInput(
            symbol="abc",
            weakening_trend=True,
            concentration_percent=Decimal("25"),
            maximum_concentration_percent=Decimal("20"),
            suggested_reduction_percent=30,
        )
    )
    assert decision.state is LifecycleState.REDUCE
    assert decision.reduction_percent == 30
    assert {item.code for item in decision.evidence} == {
        "WEAKENING_TREND",
        "CONCENTRATION_EXCEEDED",
    }


def test_position_review_holds_when_no_risk_condition_is_present() -> None:
    decision = PositionReviewEngine().review(PositionReviewInput(symbol="abc"))
    assert decision.state is LifecycleState.HOLD
    assert decision.evidence[0].code == "THESIS_INTACT"


def test_summary_and_csv_export_are_deterministic() -> None:
    engine = DecisionLifecycleEngine()
    event = engine.transition(
        recommendation_id="rec-1",
        symbol="ABC",
        occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
        previous_state=LifecycleState.WATCHLIST,
        new_state=LifecycleState.READY,
        reason="Entry quality improved.",
        evidence=(LifecycleEvidence("ENTRY", "Preferred entry zone reached."),),
        confidence=LifecycleConfidence.HIGH,
    )
    record = engine.record("rec-1")
    summary = build_lifecycle_summary((record,))
    rendered = render_lifecycle_summary(summary)
    exported = export_history_csv((event,))
    assert summary.count(LifecycleState.READY) == 1
    assert summary.total_records == 1
    assert rendered[-1] == "Execution Status: NON-EXECUTABLE DECISION INTELLIGENCE"
    assert exported.startswith("recommendation_id,symbol,occurred_at")
    assert "rec-1,ABC,2026-07-20T00:00:00+00:00,WATCHLIST,READY" in exported
    assert exported.endswith("false\n")
