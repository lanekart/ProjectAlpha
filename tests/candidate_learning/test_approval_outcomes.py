from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    ApprovalCriterionId,
    ApprovalOutcomeAnalysisEngine,
    BottleneckConclusion,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    EntryState,
    LearningLedgerRepository,
    RejectedOutcomeClassification,
    export_approval_outcomes_json,
    filter_profitable_rejections,
    group_approval_outcomes,
    render_approval_outcomes,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_profitable_rejection_and_true_negative_classification() -> None:
    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(
            _record("AAA", score=Decimal("70"), approved=False),
            _record("BBB", score=Decimal("70"), approved=False),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-5"),
            ),
        ),
    )

    assert report.profitable_rejections[0].symbol == "AAA"
    assert (
        report.profitable_rejections[0].outcome_classification
        is RejectedOutcomeClassification.TARGET_1_REACHED_REJECTION
    )
    assert report.true_negative_rejections[0].symbol == "BBB"


def test_gate_false_rejection_counts_and_interactions() -> None:
    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(
            _record("AAA", score=Decimal("70"), stop=Decimal("80"), approved=False),
            _record("BBB", score=Decimal("82"), stop=Decimal("80"), approved=False),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
        ),
    )

    evidence = next(
        item
        for item in report.gate_statistics
        if item.criterion is ApprovalCriterionId.EVIDENCE_SCORE
    )

    assert evidence.stats.candidate_count == 2
    assert evidence.stats.profitable_outcomes == 2
    assert report.interaction_statistics


def test_threshold_distance_bucket_boundaries() -> None:
    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(_record("AAA", score=Decimal("83"), approved=False),),
        outcomes=(_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),),
    )

    bucket = next(
        item
        for item in report.threshold_buckets
        if item.criterion is ApprovalCriterionId.EVIDENCE_SCORE
    )

    assert bucket.bucket == "within 2 points"


def test_winner_loser_feature_summary_and_entry_state() -> None:
    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(
            _record("AAA", score=Decimal("83"), approved=False),
            _record("BBB", score=Decimal("70"), approved=False),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-4"),
            ),
        ),
    )

    score_feature = next(
        item for item in report.feature_comparisons if item.feature == "evidence_score"
    )
    preferred = next(
        item
        for item in report.entry_state_statistics
        if item.entry_state is EntryState.PREFERRED_ENTRY
    )

    assert score_feature.winner_count == 1
    assert score_feature.loser_count == 1
    assert preferred.stats.completed_outcomes == 2


def test_delayed_entry_detection_preserves_replay_date_integrity() -> None:
    original = _record(
        "AAA",
        score=Decimal("90"),
        stop=Decimal("80"),
        approved=False,
        evaluation_date=date(2026, 1, 1),
    )
    delayed = _record(
        "AAA",
        score=Decimal("90"),
        approved=True,
        evaluation_date=date(2026, 1, 10),
        candidate_id="candidate-AAA-delayed",
    )

    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(original, delayed),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_LOST),
            _outcome("candidate-AAA-delayed", CandidateOutcomeLabel.WOULD_HAVE_WON),
        ),
    )

    opportunity = report.delayed_entry_opportunities[0]

    assert opportunity.original_replay_date == date(2026, 1, 1)
    assert opportunity.delayed_replay_date == date(2026, 1, 10)
    assert opportunity.delayed_candidate_id == "candidate-AAA-delayed"


def test_posterior_calibration_and_bottleneck_conclusion_are_deterministic() -> None:
    records = tuple(
        _record(
            f"AAA{index}",
            score=Decimal("70"),
            approved=False,
            evaluation_date=date(2026, 1, 1),
        )
        for index in range(30)
    )
    outcomes = tuple(
        _outcome(
            f"candidate-AAA{index}",
            CandidateOutcomeLabel.WOULD_HAVE_WON,
        )
        for index in range(30)
    )

    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=records,
        outcomes=outcomes,
    )

    assert sum(item.sample_count for item in report.posterior_calibration) == 30
    assert report.bottleneck_decision.conclusion in {
        BottleneckConclusion.MULTIPLE_BOTTLENECKS,
        BottleneckConclusion.INSTITUTIONAL_GATES_REJECT_MANY_WINNERS,
    }


def test_incomplete_and_unavailable_outcomes_are_not_hidden() -> None:
    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=(
            _record("AAA", approved=False),
            _record("BBB", approved=False),
        ),
        outcomes=(
            _outcome(
                "candidate-AAA",
                CandidateOutcomeLabel.DATA_MISSING,
                forward_return=None,
            ),
        ),
    )

    classifications = {
        item.symbol: item.outcome_classification for item in report.candidate_outcomes
    }

    assert classifications["AAA"] is RejectedOutcomeClassification.UNAVAILABLE_OUTCOME
    assert classifications["BBB"] is RejectedOutcomeClassification.UNAVAILABLE_OUTCOME


def test_exports_grouping_and_cli_filters(tmp_path, monkeypatch) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records(
        (
            _record("AAA", score=Decimal("70"), approved=False),
            _record("BBB", score=Decimal("70"), approved=False),
        )
    )
    repository.upsert_outcomes(
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

    report = ApprovalOutcomeAnalysisEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )
    output = tmp_path / "approval_outcomes.json"
    export_approval_outcomes_json(report, output)

    assert json.loads(output.read_text(encoding="utf-8"))["candidates_evaluated"] == 2
    assert group_approval_outcomes(report, group_by="criterion")
    assert filter_profitable_rejections(report.profitable_rejections, symbol="AAA")
    assert "Primary Bottleneck:" in "\n".join(render_approval_outcomes(report))

    result = CliRunner().invoke(app, ["replay", "approval-outcomes"])

    assert result.exit_code == 0
    assert "Outcome-Conditioned Approval Bottleneck Analysis" in result.stdout

    filtered = CliRunner().invoke(
        app,
        ["replay", "profitable-rejections", "--symbol", "AAA"],
    )

    assert filtered.exit_code == 0
    assert "AAA" in filtered.stdout


def _record(
    symbol: str,
    *,
    score: Decimal = Decimal("85"),
    stop: Decimal | None = Decimal("90"),
    approved: bool = True,
    evaluation_date: date = date(2026, 1, 1),
    candidate_id: str | None = None,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=candidate_id or f"candidate-{symbol}",
        run_id="run",
        evaluation_date=evaluation_date,
        symbol=symbol,
        final_verdict="BUY" if approved else "AVOID",
        capital_action="BUY" if approved else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("test rejection",),
        setup_type="BREAKOUT",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=score,
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("100"),
        confirmation_entry=Decimal("100"),
        risk_stop=stop,
        target_1=Decimal("110"),
        target_2=Decimal("130"),
        target_3=Decimal("140"),
        trailing_stop_plan="Trail using 2 x ATR.",
        expected_holding_period="2-4 weeks",
        indicators_active=("breakout",),
        indicator_scores={
            "price": "90",
            "relative-strength": "65",
            "volume-confirmation": "1.6",
            "distance-from-20dma": "2",
            "distance-from-50dma": "4",
            "atr-percent": "3",
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
                forward_open=Decimal("100"),
                forward_high=Decimal("115")
                if forward_return != Decimal("-5")
                else Decimal("101"),
                forward_low=Decimal("94")
                if label is CandidateOutcomeLabel.WOULD_HAVE_LOST
                else Decimal("99"),
                forward_close=Decimal("108") if forward_return is not None else None,
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=Decimal("12")
                if forward_return != Decimal("-5")
                else Decimal("1"),
                max_adverse_excursion_pct=Decimal("-2")
                if label is CandidateOutcomeLabel.WOULD_HAVE_WON
                else Decimal("-6"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
    )
