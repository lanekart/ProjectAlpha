from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    EntryTimingInput,
    EntryTimingIntelligenceEngine,
    EntryTimingState,
    EntryTimingWarningCode,
    LearningLedgerRepository,
    PriceExtensionState,
    RelativeStrengthTimingState,
    TimingDataCompleteness,
    VolumeConfirmationState,
    build_entry_timing_replay_report,
    export_entry_timing_json,
    filter_entry_timing_rows,
    group_entry_timing_report,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_assessment_is_immutable_and_enums_serialize() -> None:
    assessment = EntryTimingIntelligenceEngine().assess(
        _entry(current=Decimal("100"), support=Decimal("98"))
    )

    assert assessment.entry_state.value == "PREFERRED_ENTRY"
    assert assessment.data_completeness is TimingDataCompleteness.COMPLETE
    with pytest.raises(Exception):
        assessment.timing_score = Decimal("0")  # type: ignore[misc]


def test_entry_state_classification_boundaries() -> None:
    engine = EntryTimingIntelligenceEngine()

    assert (
        engine.assess(_entry(current=None)).entry_state
        is EntryTimingState.ENTRY_UNAVAILABLE
    )
    assert (
        engine.assess(_entry(current=Decimal("90"), stop=Decimal("95"))).entry_state
        is EntryTimingState.INVALID_ENTRY
    )
    assert (
        engine.assess(_entry(current=Decimal("99"), setup_type="breakout")).entry_state
        is EntryTimingState.SETUP_FORMING
    )
    assert (
        engine.assess(
            _entry(current=Decimal("110"), target_2=Decimal("140"), atr=Decimal("4"))
        ).entry_state
        is EntryTimingState.EXTENDED_ENTRY
    )
    assert (
        engine.assess(_entry(current=Decimal("125"))).entry_state
        is EntryTimingState.LATE_ENTRY
    )
    assert (
        engine.assess(
            _entry(current=Decimal("103"), target_2=Decimal("113"))
        ).entry_state
        is EntryTimingState.EARLY_ENTRY
    )
    assert (
        engine.assess(
            _entry(current=Decimal("104"), target_2=Decimal("120"))
        ).entry_state
        is EntryTimingState.AGGRESSIVE_ENTRY
    )
    assert (
        engine.assess(_entry(current=Decimal("102"))).entry_state
        is EntryTimingState.PREFERRED_ENTRY
    )
    assert (
        engine.assess(
            _entry(
                current=Decimal("102"),
                setup_type="breakout",
                volume=VolumeConfirmationState.CONFIRMED_EXPANSION,
            )
        ).entry_state
        is EntryTimingState.CONFIRMATION_ENTRY
    )


def test_structural_calculations_and_context_states() -> None:
    assessment = EntryTimingIntelligenceEngine().assess(
        _entry(
            current=Decimal("105"),
            support=Decimal("100"),
            breakout=Decimal("102"),
            dma_20=Decimal("101"),
            dma_50=Decimal("99"),
            atr=Decimal("2.5"),
            volume=VolumeConfirmationState.WEAK_CONFIRMATION,
            relative_strength=RelativeStrengthTimingState.UNDERPERFORMING,
        )
    )

    assert assessment.distance_from_support_pct == Decimal("5.00")
    assert assessment.distance_from_support_atr == Decimal("2.00")
    assert assessment.distance_from_breakout_pct == Decimal("2.94")
    assert assessment.distance_from_20dma_pct == Decimal("3.96")
    assert assessment.distance_from_50dma_pct == Decimal("6.06")
    assert assessment.atr_percent == Decimal("2.38")
    assert assessment.price_extension_state is PriceExtensionState.MILDLY_EXTENDED
    assert EntryTimingWarningCode.WEAK_VOLUME_CONFIRMATION in assessment.timing_warnings
    assert (
        EntryTimingWarningCode.UNDERPERFORMING_RELATIVE_STRENGTH
        in assessment.timing_warnings
    )


def test_setup_specific_logic_for_current_setup_families() -> None:
    engine = EntryTimingIntelligenceEngine()

    assert (
        engine.assess(_entry(setup_type="retracement")).entry_state
        is EntryTimingState.PREFERRED_ENTRY
    )
    assert (
        engine.assess(
            _entry(
                setup_type="reversal",
                volume=VolumeConfirmationState.CONFIRMED_EXPANSION,
            )
        ).entry_state
        is EntryTimingState.CONFIRMATION_ENTRY
    )
    assert (
        engine.assess(_entry(setup_type="trend continuation")).entry_state
        is EntryTimingState.PREFERRED_ENTRY
    )
    assert (
        engine.assess(
            _entry(setup_type="unknown", current=Decimal("106"), atr=None)
        ).entry_state
        is EntryTimingState.SETUP_FORMING
    )


def test_replay_diagnostics_and_approval_counts_are_preserved() -> None:
    records = (
        _record("AAA", approved=False, score=Decimal("80")),
        _record("BBB", approved=True, score=Decimal("90")),
    )
    report = build_entry_timing_replay_report(
        records=records,
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-4"),
            ),
        ),
    )

    assert report.candidates_evaluated == 2
    assert report.completed_outcomes == 2
    assert report.approval_count_before == 1
    assert report.approval_count_after == 1
    assert report.state_performance
    assert report.winner_loser_comparison
    assert report.profitable_rejection_rows[0].assessment.symbol == "AAA"
    assert report.conclusion.supporting_metrics


def test_entry_timing_exports_grouping_and_cli_filters(tmp_path, monkeypatch) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records(
        (
            _record("AAA", approved=False, score=Decimal("80")),
            _record("BBB", approved=True, score=Decimal("90")),
        )
    )
    repository.upsert_outcomes(
        (
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        )
    )
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )
    report = build_entry_timing_replay_report(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )
    output = tmp_path / "entry_timing.json"

    export_entry_timing_json(report, output)
    filtered = filter_entry_timing_rows(report.rows, profitable_only=True)

    assert json.loads(output.read_text(encoding="utf-8"))["candidates_evaluated"] == 2
    assert group_entry_timing_report(report, group_by="entry-state")
    assert filtered[0].assessment.symbol == "AAA"

    result = CliRunner().invoke(app, ["replay", "entry-timing"])
    assert result.exit_code == 0
    assert "Entry Timing Intelligence Replay Report" in result.stdout

    failures = CliRunner().invoke(
        app,
        ["replay", "entry-timing-failures", "--profitable-only"],
    )
    assert failures.exit_code == 0
    assert "AAA" in failures.stdout


def _entry(
    *,
    current: Decimal | None = Decimal("102"),
    support: Decimal | None = Decimal("100"),
    stop: Decimal | None = Decimal("95"),
    breakout: Decimal | None = Decimal("100"),
    target_1: Decimal | None = Decimal("112"),
    target_2: Decimal | None = Decimal("130"),
    dma_20: Decimal | None = Decimal("100"),
    dma_50: Decimal | None = Decimal("98"),
    atr: Decimal | None = Decimal("2"),
    setup_type: str | None = "retracement",
    volume: VolumeConfirmationState = VolumeConfirmationState.CONFIRMED_EXPANSION,
    relative_strength: RelativeStrengthTimingState = (
        RelativeStrengthTimingState.OUTPERFORMING
    ),
) -> EntryTimingInput:
    return EntryTimingInput(
        symbol="AAA",
        evaluation_date=date(2026, 1, 1),
        setup_type=setup_type,
        current_price=current,
        reference_entry=current,
        structural_support=support,
        structural_resistance=target_1,
        breakout_level=breakout,
        retracement_low=support,
        retracement_high=current,
        recent_swing_low=support,
        recent_swing_high=target_1,
        dma_20=dma_20,
        dma_50=dma_50,
        dma_200=None,
        atr=atr,
        stop_loss=stop,
        target_1=target_1,
        target_2=target_2,
        market_regime="BULLISH",
        sector_regime="IT",
        setup_age_bars=3,
        volume_confirmation_state=volume,
        relative_strength_state=relative_strength,
    )


def _record(
    symbol: str,
    *,
    approved: bool,
    score: Decimal,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict="BUY" if approved else "AVOID",
        capital_action="BUY" if approved else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("evidence_score",),
        setup_type="RETRACEMENT",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=score,
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("102"),
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
                forward_low=Decimal("94")
                if label is CandidateOutcomeLabel.WOULD_HAVE_LOST
                else Decimal("101"),
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
