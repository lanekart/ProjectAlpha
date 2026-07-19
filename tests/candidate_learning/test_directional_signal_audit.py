from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    DirectionalOutcomeLabel,
    DirectionalSignalConclusion,
    DirectionalSignalQualityAuditEngine,
    LearningLedgerRepository,
    LineageOverlapReason,
    export_directional_signal_audit_csv,
    export_directional_signal_audit_json,
    group_directional_signal_audit,
    render_directional_signal_audit,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_outcome_quality_absolute_and_benchmark_relative_classification() -> None:
    report = DirectionalSignalQualityAuditEngine().analyze(
        records=(
            _record("WIN", verdict="BUY", benchmark=Decimal("2")),
            _record("LOSS", verdict="BUY", benchmark=Decimal("-1")),
            _record("RECOVER", verdict="BUY", benchmark=Decimal("1")),
        ),
        outcomes=(
            _outcome("candidate-WIN", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-LOSS",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-5"),
            ),
            _outcome(
                "candidate-RECOVER",
                CandidateOutcomeLabel.WOULD_HAVE_WON,
                stop=True,
            ),
        ),
    )
    by_symbol = {row.symbol: row for row in report.candidate_rows}

    assert by_symbol["WIN"].outcome_label is DirectionalOutcomeLabel.CLEAN_WIN
    assert by_symbol["WIN"].excess_return == Decimal("6.0000")
    assert by_symbol["LOSS"].outcome_label is DirectionalOutcomeLabel.CLEAN_LOSS
    assert (
        by_symbol["RECOVER"].outcome_label
        is DirectionalOutcomeLabel.STOPPED_THEN_RECOVERED
    )


def test_directional_accuracy_ranking_and_calibration_are_reported() -> None:
    report = DirectionalSignalQualityAuditEngine().analyze(
        records=(
            _record("A", verdict="BUY", score=Decimal("95"), posterior="0.70"),
            _record("B", verdict="BUY", score=Decimal("90"), posterior="0.65"),
            _record("C", verdict="AVOID", score=Decimal("60"), posterior="0.40"),
            _record("D", verdict="SELL", score=Decimal("55"), posterior="0.35"),
        ),
        outcomes=(
            _outcome("candidate-A", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-B",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-4"),
            ),
            _outcome("candidate-C", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-D",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-6"),
            ),
        ),
    )
    recommendation = next(
        item
        for item in report.ranking_metrics
        if item.score_name == "recommendation_score"
    )

    assert report.all_accuracy.buy_precision == Decimal("0.5000")
    assert report.all_accuracy.profitable_avoid_count == 1
    assert recommendation.roc_auc is not None
    assert report.calibration


def test_lineage_overlap_explains_expectancy_posterior_identity() -> None:
    report = DirectionalSignalQualityAuditEngine().analyze(
        records=(
            _record("A", score=Decimal("70")),
            _record("B", score=Decimal("70")),
        ),
        outcomes=(
            _outcome("candidate-A", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-B",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-3"),
            ),
        ),
    )

    assert report.lineage_overlap[0].reason in {
        LineageOverlapReason.SAME_SOURCE_FEATURES,
        LineageOverlapReason.SHARED_MISSING_DATA,
    }
    assert "expectancy" in "\n".join(
        group_directional_signal_audit(report, group_by="lineage")
    )


def test_setup_regime_horizon_components_and_counterfactuals() -> None:
    report = DirectionalSignalQualityAuditEngine().analyze(
        records=(
            _record("A", setup="MOMENTUM CONTINUATION", regime="NEUTRAL"),
            _record(
                "B",
                setup="MOMENTUM CONTINUATION",
                regime="NEUTRAL",
                score=Decimal("70"),
            ),
            _record("C", setup="TREND FAILURE", regime="NEGATIVE", score=Decimal("55")),
        ),
        outcomes=(
            _outcome("candidate-A", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-B",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-5"),
            ),
            _outcome(
                "candidate-C",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-7"),
            ),
        ),
    )

    assert report.setup_family
    assert report.market_regime
    assert report.horizons
    assert report.components
    assert report.counterfactuals


def test_exports_cli_and_policy_integrity(tmp_path, monkeypatch) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records(
        (
            _record("AAA", verdict="BUY", approved=True, score=Decimal("90")),
            _record("BBB", verdict="AVOID", score=Decimal("60")),
        )
    )
    ledger.upsert_outcomes(
        (
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome(
                "candidate-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                Decimal("-4"),
            ),
        )
    )
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )
    report = DirectionalSignalQualityAuditEngine().analyze(
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    json_path = tmp_path / "directional.json"
    csv_path = tmp_path / "directional.csv"

    export_directional_signal_audit_json(report, json_path)
    export_directional_signal_audit_csv(report, csv_path)
    cli = CliRunner().invoke(app, ["replay", "directional-signal-audit"])
    grouped = CliRunner().invoke(
        app,
        ["replay", "directional-signal-audit", "--group-by", "setup"],
    )
    ranking = CliRunner().invoke(app, ["replay", "signal-ranking"])

    assert json.loads(json_path.read_text(encoding="utf-8"))["candidate_count"] == 2
    assert "candidate_id" in csv_path.read_text(encoding="utf-8")
    assert "Policy Integrity" in "\n".join(render_directional_signal_audit(report))
    assert report.raw_approval_count_before == report.raw_approval_count_after
    assert report.strict_approval_count_before == report.strict_approval_count_after
    assert report.verdicts_unchanged is True
    assert report.recommendation_scores_unchanged is True
    assert report.timing_states_unchanged is True
    assert cli.exit_code == 0
    assert "Directional Signal Quality Audit" in cli.stdout
    assert grouped.exit_code == 0
    assert "Grouped By setup" in grouped.stdout
    assert ranking.exit_code == 0


def test_insufficient_sample_conclusion_is_deterministic() -> None:
    report = DirectionalSignalQualityAuditEngine().analyze(records=(), outcomes=())

    assert (
        report.decision.primary_conclusion
        is DirectionalSignalConclusion.INSUFFICIENT_EVIDENCE_FOR_DIRECTIONAL_CONCLUSION
    )


def _record(
    symbol: str,
    *,
    verdict: str = "BUY",
    score: Decimal = Decimal("85"),
    approved: bool = False,
    setup: str = "MOMENTUM CONTINUATION",
    regime: str = "NEUTRAL",
    benchmark: Decimal | None = None,
    posterior: str = "0.55",
) -> CandidateDecisionRecord:
    indicator_scores = {
        "trend": str(score),
        "volume": "65",
        "relative-strength": "70",
        "posterior-probability": posterior,
        "atr": "2",
        "dma-20": "100",
        "dma-50": "98",
        "volume-confirmation": "1.6",
    }
    if benchmark is not None:
        indicator_scores["benchmark-return"] = str(benchmark)
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict=verdict,
        capital_action="BUY" if verdict in {"BUY", "STRONG_BUY"} else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("test rejection",),
        setup_type=setup,
        market_regime=regime,
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
        indicators_active=("trend", "volume", "relative-strength"),
        indicator_scores=indicator_scores,
        evidence_layers=("Price/Volume",),
        explanation="Trade invalid if daily close is below 20-DMA.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _outcome(
    candidate_id: str,
    label: CandidateOutcomeLabel,
    forward_return: Decimal | None = Decimal("8"),
    *,
    stop: bool = False,
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
                if label is CandidateOutcomeLabel.WOULD_HAVE_LOST or stop
                else Decimal("101"),
                forward_close=Decimal("110"),
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=Decimal("12"),
                max_adverse_excursion_pct=Decimal("-9") if stop else Decimal("-2"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=(
                    stop or label is CandidateOutcomeLabel.WOULD_HAVE_LOST
                ),
                outcome_label=label,
            ),
            CandidateForwardWindowOutcome(
                window="5d",
                forward_open=Decimal("102"),
                forward_high=Decimal("110"),
                forward_low=Decimal("99"),
                forward_close=Decimal("106"),
                forward_return_pct_from_close=Decimal("3"),
                forward_return_pct_from_entry=Decimal("3"),
                max_favourable_excursion_pct=Decimal("6"),
                max_adverse_excursion_pct=Decimal("-1"),
                target_1_touched=False,
                risk_stop_touched=False,
                outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON,
            ),
        ),
    )
