from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    ApprovalBaselineAuditEngine,
    ApprovalBaselineConclusion,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    EntryTimingState,
    EntryTimingValidationEngine,
    LearningLedgerRepository,
    build_entry_timing_replay_report,
    export_entry_timing_validation_csv,
    export_entry_timing_validation_json,
    group_entry_timing_validation_report,
    render_approval_baseline_audit,
    render_entry_timing_validation_report,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_approval_baseline_audit_reconciles_different_concepts() -> None:
    records = (
        _record("AAA", approved=True, score=Decimal("70")),
        _record("BBB", approved=False, current=Decimal("125")),
    )
    outcomes = (
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
        _outcome(
            "candidate-BBB",
            CandidateOutcomeLabel.WOULD_HAVE_WON,
            forward_return=Decimal("6"),
        ),
    )
    timing_report = build_entry_timing_replay_report(
        records=records,
        outcomes=outcomes,
    )

    comparison = ApprovalBaselineAuditEngine().compare(
        records=records,
        outcomes=outcomes,
        timing_report=timing_report,
    )
    rendered = "\n".join(render_approval_baseline_audit(comparison))

    assert (
        comparison.conclusion is ApprovalBaselineConclusion.DIFFERENT_APPROVAL_CONCEPTS
    )
    assert comparison.sources[0].approval_count != comparison.sources[1].approval_count
    assert "different approval concepts" in rendered
    assert "approval regression" not in rendered.lower()


def test_entry_timing_validation_reports_state_outcomes_and_attribution() -> None:
    records = (
        _record("WIN", approved=False, current=Decimal("102")),
        _record("LOSS", approved=True, current=Decimal("125")),
        _record("FORM", approved=False, current=Decimal("99"), setup_type="breakout"),
    )
    outcomes = (
        _outcome("candidate-WIN", CandidateOutcomeLabel.WOULD_HAVE_WON),
        _outcome(
            "candidate-LOSS",
            CandidateOutcomeLabel.WOULD_HAVE_LOST,
            forward_return=Decimal("-12"),
        ),
        _outcome("candidate-FORM", CandidateOutcomeLabel.WOULD_HAVE_WON),
    )

    report = EntryTimingValidationEngine().audit(records=records, outcomes=outcomes)
    preferred = next(
        item
        for item in report.state_validation
        if item.entry_state is EntryTimingState.PREFERRED_ENTRY
    )
    late = next(
        item
        for item in report.state_validation
        if item.entry_state is EntryTimingState.LATE_ENTRY
    )
    attribution = next(
        item
        for item in report.profitable_rejection_attribution
        if item.entry_state is EntryTimingState.PREFERRED_ENTRY
    )
    rendered = "\n".join(render_entry_timing_validation_report(report))

    assert preferred.completed_outcomes == 1
    assert preferred.success_rate == Decimal("1.0000")
    assert preferred.average_realised_reward_risk is not None
    assert late.failure_rate == Decimal("1.0000")
    assert attribution.candidate_count == 1
    assert report.winner_loser_comparison
    assert report.incremental_value
    assert report.boundary_audit
    assert "Policy Integrity" in rendered
    assert "State-Level Outcome Table" in rendered


def test_entry_timing_validation_grouping_and_exports(tmp_path) -> None:
    report = EntryTimingValidationEngine().audit(
        records=(
            _record("AAA", approved=False),
            _record("BBB", approved=True, current=Decimal("125")),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-10"),
            ),
        ),
    )
    json_path = tmp_path / "entry_timing_audit.json"
    csv_path = tmp_path / "entry_timing_audit.csv"

    export_entry_timing_validation_json(report, json_path)
    export_entry_timing_validation_csv(report, csv_path)

    assert group_entry_timing_validation_report(report, group_by="entry-state")
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["baseline_comparison"][
            "conclusion"
        ]
        == "DIFFERENT_APPROVAL_CONCEPTS"
    )
    assert "section" in csv_path.read_text(encoding="utf-8")


def test_cli_entry_timing_audit_and_approval_baseline_audit(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records(
        (
            _record("AAA", approved=False),
            _record("BBB", approved=True, current=Decimal("125")),
        )
    )
    ledger.upsert_outcomes(
        (
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-10"),
            ),
        )
    )
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )

    audit = CliRunner().invoke(
        app,
        ["replay", "entry-timing-audit", "--profitable-rejections"],
    )
    baseline = CliRunner().invoke(app, ["replay", "approval-baseline-audit"])
    output = tmp_path / "audit.json"
    export = CliRunner().invoke(
        app,
        [
            "replay",
            "entry-timing-audit",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert audit.exit_code == 0
    assert "Entry Timing Validation and Gate Attribution Audit" in audit.stdout
    assert "Grouped By profitable-rejections" in audit.stdout
    assert baseline.exit_code == 0
    assert "DIFFERENT_APPROVAL_CONCEPTS" in baseline.stdout
    assert export.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["candidates_evaluated"] == 2


def _record(
    symbol: str,
    *,
    approved: bool,
    current: Decimal = Decimal("102"),
    setup_type: str = "retracement",
    score: Decimal | None = None,
) -> CandidateDecisionRecord:
    strategy_score = score or (Decimal("90") if approved else Decimal("80"))
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict="BUY" if approved else "AVOID",
        capital_action="BUY" if approved else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("evidence_score",),
        setup_type=setup_type,
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=strategy_score,
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("100"),
        entry_zone_high=current,
        confirmation_entry=current,
        risk_stop=Decimal("95"),
        target_1=Decimal("112"),
        target_2=Decimal("130"),
        target_3=Decimal("140"),
        trailing_stop_plan="Trail using 2 x ATR.",
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
        explanation="Trade invalid if daily close is below 20-DMA.",
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
                max_adverse_excursion_pct=Decimal("-2"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
    )
