from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    ApprovalCriterionId,
    ApprovalDiagnosticsEngine,
    ApprovalReadinessState,
    ApprovalRejectionReasonCode,
    CandidateDecisionRecord,
    LearningLedgerRepository,
    filter_diagnostics,
    render_approval_diagnostics,
)
from alpha.candidate_learning.models import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.cli import app


def test_approval_criteria_pass_at_exact_thresholds() -> None:
    records = tuple(_record(f"AAA{index}") for index in range(60))
    outcomes = tuple(
        _outcome(f"candidate-AAA{index}", CandidateOutcomeLabel.WOULD_HAVE_WON)
        for index in range(60)
    )
    summary = ApprovalDiagnosticsEngine().build(
        records=records,
        outcomes=outcomes,
    )

    diagnostic = summary.diagnostics[0]
    failed = {criterion.value for criterion in diagnostic.failed_criteria}
    assert ApprovalCriterionId.EVIDENCE_SCORE.value not in failed
    assert ApprovalCriterionId.STOP_DISTANCE.value not in failed
    assert ApprovalCriterionId.HISTORICAL_SAMPLES.value not in failed
    assert diagnostic.approval_margin > Decimal("0")


def test_missing_trade_plan_fields_are_reported_as_binary_missing() -> None:
    records = (_record("AAA", target_2=None, trailing_stop_plan=None),) + tuple(
        _record(f"BBB{index}") for index in range(60)
    )
    outcomes = (
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
    ) + tuple(
        _outcome(
            f"candidate-BBB{index}",
            CandidateOutcomeLabel.WOULD_HAVE_WON,
        )
        for index in range(60)
    )
    summary = ApprovalDiagnosticsEngine().build(
        records=records,
        outcomes=outcomes,
    )

    diagnostic = summary.diagnostics[0]

    assert diagnostic.approval_readiness is ApprovalReadinessState.INCOMPLETE_TRADE_PLAN
    assert ApprovalCriterionId.TARGETS_AVAILABLE in diagnostic.failed_criteria
    assert ApprovalCriterionId.ATR_AVAILABLE in diagnostic.failed_criteria
    assert diagnostic.primary_rejection_reason in {
        ApprovalRejectionReasonCode.MULTIPLE_MATERIAL_FAILURES,
        ApprovalRejectionReasonCode.INCOMPLETE_TARGETS,
    }


def test_numeric_threshold_gap_is_exact() -> None:
    records = (_record("AAA", score=Decimal("81")),) + tuple(
        _record(f"BBB{index}") for index in range(60)
    )
    outcomes = (
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
    ) + tuple(
        _outcome(
            f"candidate-BBB{index}",
            CandidateOutcomeLabel.WOULD_HAVE_WON,
        )
        for index in range(60)
    )
    summary = ApprovalDiagnosticsEngine().build(
        records=records,
        outcomes=outcomes,
    )

    score_result = next(
        result
        for result in summary.diagnostics[0].criterion_results
        if result.criterion_id is ApprovalCriterionId.EVIDENCE_SCORE
    )

    assert score_result.threshold_gap == "shortfall 4.00 points"


def test_strong_evidence_exception_bypasses_sample_requirement() -> None:
    summary = ApprovalDiagnosticsEngine().build(
        records=(
            _record(
                "AAA",
                evidence_layers=("Price/Volume", "strong-evidence-exception"),
            ),
        ),
        outcomes=(_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),),
    )

    historical_samples = next(
        result
        for result in summary.diagnostics[0].criterion_results
        if result.criterion_id is ApprovalCriterionId.HISTORICAL_SAMPLES
    )
    exception = next(
        result
        for result in summary.diagnostics[0].criterion_results
        if result.criterion_id is ApprovalCriterionId.STRONG_EVIDENCE_EXCEPTION
    )

    assert historical_samples.passed is True
    assert exception.applicable is True
    assert exception.passed is True


def test_nearest_candidate_ranking_is_deterministic() -> None:
    summary = ApprovalDiagnosticsEngine().build(
        records=(
            _record("BBB", score=Decimal("84")),
            _record("AAA", score=Decimal("84")),
        ),
        outcomes=(
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
        ),
    )

    assert summary.nearest_candidates[0].symbol == "AAA"
    assert summary.nearest_candidates[0].nearest_to_approval_rank == 1


def test_aggregate_summary_and_rendering_show_no_deployment_status() -> None:
    summary = ApprovalDiagnosticsEngine().build(
        records=(_record("AAA", score=Decimal("70")),),
        outcomes=(_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_LOST),),
    )
    output = "\n".join(render_approval_diagnostics(summary))

    assert summary.total_candidates == 1
    assert "Institutional Approval Diagnostics" in output
    assert "Policy Integrity: no approval thresholds were changed." in output
    assert "Institutional Deployment Status: NO DEPLOYABLE TRADE" in output


def test_failure_filters_select_near_approval_and_symbol() -> None:
    summary = ApprovalDiagnosticsEngine().build(
        records=(
            _record("AAA", score=Decimal("84")),
            _record("BBB", score=Decimal("70")),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        ),
    )

    filtered = filter_diagnostics(summary.diagnostics, symbol="AAA")

    assert len(filtered) == 1
    assert filtered[0].symbol == "AAA"


def test_cli_approval_diagnostics_and_json_export(tmp_path, monkeypatch) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records((_record("AAA", score=Decimal("70")),))
    ledger.upsert_outcomes(
        (_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_LOST),)
    )
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )

    result = CliRunner().invoke(app, ["replay", "approval-diagnostics"])

    assert result.exit_code == 0
    assert "Institutional Approval Diagnostics" in result.stdout

    output = tmp_path / "approval.json"
    export_result = CliRunner().invoke(
        app,
        [
            "replay",
            "approval-diagnostics",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert export_result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))[0]["symbol"] == "AAA"


def _record(
    symbol: str,
    *,
    score: Decimal = Decimal("85"),
    stop: Decimal | None = Decimal("90"),
    target_2: Decimal | None = Decimal("130"),
    trailing_stop_plan: str | None = "Trail using 2 x ATR.",
    evidence_layers: tuple[str, ...] = ("Price/Volume",),
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=True,
        rejection_reasons=(),
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
        target_1=Decimal("120"),
        target_2=target_2,
        target_3=Decimal("140"),
        trailing_stop_plan=trailing_stop_plan,
        expected_holding_period="2-4 weeks",
        indicators_active=("breakout",),
        indicator_scores={"price": "90"},
        evidence_layers=evidence_layers,
        explanation="Trade invalid if daily close is below 20-DMA.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _outcome(
    candidate_id: str,
    label: CandidateOutcomeLabel,
) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.replace("candidate-", ""),
        evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("130"),
                forward_low=Decimal("95"),
                forward_close=Decimal("120"),
                forward_return_pct_from_close=Decimal("20"),
                forward_return_pct_from_entry=Decimal("0.10"),
                max_favourable_excursion_pct=Decimal("30"),
                max_adverse_excursion_pct=Decimal("-5"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
    )
