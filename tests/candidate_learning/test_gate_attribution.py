from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    ApprovalCriterionId,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    EntryTimingState,
    GateAttributionConclusion,
    GateAttributionFinding,
    GateCategory,
    GateOverlapClassification,
    GateScope,
    LearningLedgerRepository,
    NonEntryGateAttributionEngine,
    authoritative_gate_inventory,
    export_gate_attribution_csv,
    export_gate_attribution_json,
    export_gate_candidate_audit_csv,
    group_gate_attribution_report,
    render_gate_attribution_report,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_authoritative_gate_inventory_marks_non_entry_and_mixed_gates() -> None:
    inventory = authoritative_gate_inventory()
    by_id = {item.gate_id: item for item in inventory}

    assert set(by_id) == set(ApprovalCriterionId)
    assert by_id[ApprovalCriterionId.EVIDENCE_SCORE].gate_scope is GateScope.NON_ENTRY
    assert by_id[ApprovalCriterionId.ENTRY_AVAILABLE].gate_scope is GateScope.MIXED
    assert (
        by_id[ApprovalCriterionId.POSTERIOR_PROBABILITY].gate_category
        is GateCategory.PROBABILITY_CALIBRATION
    )


def test_primary_secondary_universe_and_policy_invariants_are_preserved() -> None:
    records = (
        _record("WIN", score=Decimal("70"), approved=False),
        _record("LOSS", score=Decimal("70"), approved=False, current=Decimal("125")),
        _record("RAW", score=Decimal("70"), approved=True),
    )
    outcomes = (
        _outcome("candidate-WIN", CandidateOutcomeLabel.WOULD_HAVE_WON),
        _outcome(
            "candidate-LOSS",
            CandidateOutcomeLabel.WOULD_HAVE_LOST,
            forward_return=Decimal("-10"),
        ),
        _outcome("candidate-RAW", CandidateOutcomeLabel.WOULD_HAVE_WON),
    )

    report = NonEntryGateAttributionEngine().analyze(
        records=records,
        outcomes=outcomes,
    )

    assert report.primary_universe_count == 2
    assert report.secondary_universe_count == 1
    assert report.raw_approval_count_before == report.raw_approval_count_after == 1
    assert (
        report.strict_approval_count_before == report.strict_approval_count_after == 0
    )
    assert {row.entry_state for row in report.candidate_rows} == {
        EntryTimingState.PREFERRED_ENTRY,
        EntryTimingState.LATE_ENTRY,
    }


def test_gate_attribution_false_negative_and_downside_protection() -> None:
    report = NonEntryGateAttributionEngine().analyze(
        records=(
            _record("WIN", score=Decimal("70"), approved=False),
            _record("LOSS", score=Decimal("70"), approved=False),
            _record("PASS", score=Decimal("95"), approved=False),
        ),
        outcomes=(
            _outcome("candidate-WIN", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-LOSS",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-9"),
            ),
            _outcome("candidate-PASS", CandidateOutcomeLabel.WOULD_HAVE_WON),
        ),
    )
    evidence = next(
        item
        for item in report.primary_attribution
        if item.gate_id is ApprovalCriterionId.EVIDENCE_SCORE
    )

    assert evidence.profitable_rejected_candidates >= 1
    assert evidence.true_negative_rejected_candidates >= 1
    assert evidence.economic_impact.gross_missed_upside > Decimal("0")
    assert evidence.economic_impact.gross_avoided_downside > Decimal("0")
    assert evidence.findings


def test_overlap_incremental_rankings_and_interactions_are_deterministic() -> None:
    records = tuple(
        _record(
            f"AAA{index}",
            score=Decimal("70"),
            approved=False,
            target_2=None if index % 2 == 0 else Decimal("130"),
        )
        for index in range(6)
    )
    outcomes = tuple(
        _outcome(
            f"candidate-AAA{index}",
            CandidateOutcomeLabel.WOULD_HAVE_WON
            if index % 3 == 0
            else CandidateOutcomeLabel.WOULD_HAVE_LOST,
            forward_return=Decimal("8") if index % 3 == 0 else Decimal("-6"),
        )
        for index in range(6)
    )

    report = NonEntryGateAttributionEngine().analyze(
        records=records,
        outcomes=outcomes,
    )

    assert report.overlap_matrix
    assert report.interaction_clusters
    assert report.incremental_value
    assert report.rankings.opportunity_cost
    assert report.rankings.downside_protection
    assert report.overlap_matrix[0].classification in set(GateOverlapClassification)


def test_missing_data_burden_and_trade_plan_gate_are_reported() -> None:
    report = NonEntryGateAttributionEngine().analyze(
        records=(_record("MISS", approved=False, stop=None, trailing_stop_plan=None),),
        outcomes=(
            _outcome(
                "candidate-MISS",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-7"),
            ),
        ),
    )
    stop_gate = next(
        item
        for item in report.secondary_attribution
        if item.gate_id is ApprovalCriterionId.STOP_DISTANCE
    )
    stop_available = next(
        item
        for item in report.secondary_attribution
        if item.gate_id is ApprovalCriterionId.STOP_AVAILABLE
    )

    assert report.secondary_universe_count == 1
    assert stop_gate.candidates_with_missing_inputs == 1
    assert GateAttributionFinding.GATE_IS_DATA_LIMITED in stop_gate.findings
    assert stop_available.gate_category is GateCategory.TRADE_PLAN_QUALITY


def test_rendering_grouping_exports_and_cli(tmp_path, monkeypatch) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records(
        (
            _record("AAA", score=Decimal("70"), approved=False),
            _record("BBB", score=Decimal("70"), approved=False),
        )
    )
    ledger.upsert_outcomes(
        (
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-5"),
            ),
        )
    )
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )
    report = NonEntryGateAttributionEngine().analyze(
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    json_path = tmp_path / "gate_attribution.json"
    csv_path = tmp_path / "gate_attribution.csv"
    candidate_csv = tmp_path / "candidate_export.csv"

    export_gate_attribution_json(report, json_path)
    export_gate_attribution_csv(report, csv_path)
    export_gate_candidate_audit_csv(report.candidate_rows, candidate_csv)

    rendered = "\n".join(render_gate_attribution_report(report))
    cli = CliRunner().invoke(app, ["replay", "gate-attribution"])
    grouped = CliRunner().invoke(
        app,
        ["replay", "gate-attribution", "--group-by", "overlap"],
    )
    opportunity = CliRunner().invoke(app, ["replay", "gate-opportunity-cost"])

    assert "Non-Entry Gate Attribution Intelligence" in rendered
    assert group_gate_attribution_report(report, group_by="economic-impact")
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["candidates_evaluated"] == 2
    )
    assert "section" in csv_path.read_text(encoding="utf-8")
    assert "failed_non_entry_gates" in candidate_csv.read_text(encoding="utf-8")
    assert cli.exit_code == 0
    assert "Policy Integrity" in cli.stdout
    assert grouped.exit_code == 0
    assert "Gate Attribution Grouped By overlap" in grouped.stdout
    assert opportunity.exit_code == 0


def test_empty_replay_is_diagnostic_not_policy_change() -> None:
    report = NonEntryGateAttributionEngine().analyze(records=(), outcomes=())

    assert report.candidates_evaluated == 0
    assert (
        report.decision.primary_conclusion
        is GateAttributionConclusion.INSUFFICIENT_EVIDENCE
    )
    assert report.raw_approval_count_before == report.raw_approval_count_after == 0
    assert (
        report.strict_approval_count_before == report.strict_approval_count_after == 0
    )


def _record(
    symbol: str,
    *,
    score: Decimal = Decimal("85"),
    stop: Decimal | None = Decimal("95"),
    approved: bool = False,
    current: Decimal = Decimal("102"),
    target_1: Decimal | None = Decimal("112"),
    target_2: Decimal | None = Decimal("130"),
    target_3: Decimal | None = Decimal("140"),
    trailing_stop_plan: str | None = "Trail using 2 x ATR.",
    explanation: str = "Trade invalid if daily close is below 20-DMA.",
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict="BUY" if approved else "AVOID",
        capital_action="BUY" if approved else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("test rejection",),
        setup_type="RETRACEMENT",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=score,
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("100"),
        entry_zone_high=current,
        confirmation_entry=current,
        risk_stop=stop,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        trailing_stop_plan=trailing_stop_plan,
        expected_holding_period="2-4 weeks",
        indicators_active=("retracement",),
        indicator_scores={
            "atr": "2",
            "dma-20": "100",
            "dma-50": "98",
            "volume-confirmation": "1.6",
            "relative-strength": "65",
        },
        evidence_layers=("Price/Volume",),
        explanation=explanation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _outcome(
    candidate_id: str,
    label: CandidateOutcomeLabel,
    *,
    forward_return: Decimal | None = Decimal("8"),
) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.replace("candidate-", ""),
        evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("102"),
                forward_high=Decimal("132"),
                forward_low=(
                    Decimal("94")
                    if label is CandidateOutcomeLabel.WOULD_HAVE_LOST
                    else Decimal("101")
                ),
                forward_close=Decimal("110"),
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=Decimal("12"),
                max_adverse_excursion_pct=(
                    Decimal("-2")
                    if label is CandidateOutcomeLabel.WOULD_HAVE_WON
                    else Decimal("-8")
                ),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
    )
