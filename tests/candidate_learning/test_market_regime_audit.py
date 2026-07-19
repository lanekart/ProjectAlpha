from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    LearningLedgerRepository,
)
from alpha.candidate_learning.market_regime_audit import (
    MarketRegimeAuditConfig,
    MarketRegimeAuditEngine,
    NeutralConcentrationCause,
    ReferenceMarketState,
    RegimeAuditConclusion,
    RegimeJoinMethod,
    RetracementRegimeFinding,
    export_market_regime_audit_csv,
    export_market_regime_audit_json,
    group_market_regime_audit,
    render_market_regime_audit,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_policy_integrity_and_production_regime_inventory() -> None:
    records = _records()
    outcomes = _outcomes()
    report = MarketRegimeAuditEngine().analyze(records=records, outcomes=outcomes)

    assert report.production_inventory
    assert report.recommendation_scores_unchanged is True
    assert report.verdicts_unchanged is True
    assert report.regime_records_unchanged is True
    assert report.timing_states_unchanged is True
    assert report.raw_approvals_unchanged is True
    assert report.strict_approvals_unchanged is True
    assert report.allocations_unchanged is True


def test_timestamp_attachment_and_missing_neutral_detection() -> None:
    report = MarketRegimeAuditEngine().analyze(
        records=(
            _record("AAA", regime="NEUTRAL", data_quality="MISSING REGIME INPUT"),
            _record("BBB", regime=None),
        ),
        outcomes=(
            _outcome("candidate-AAA", Decimal("4")),
            _outcome("candidate-BBB", Decimal("-3")),
        ),
    )
    by_symbol = {item.symbol: item for item in report.attachments}

    assert by_symbol["AAA"].join_method is RegimeJoinMethod.DEFAULTED_NEUTRAL
    assert by_symbol["BBB"].join_method is RegimeJoinMethod.MISSING
    assert (
        NeutralConcentrationCause.DEFAULT_NEUTRAL_FALLBACK
        in report.decision.neutral_concentration_causes
    )


def test_reference_comparison_transitions_and_episode_detection() -> None:
    report = MarketRegimeAuditEngine().analyze(
        records=(
            _record("AAA", regime="NEUTRAL", benchmark=Decimal("-6"), day=1),
            _record("BBB", regime="BULL", benchmark=Decimal("6"), day=2),
            _record("CCC", regime="BEAR", benchmark=Decimal("-9"), day=3),
        ),
        outcomes=(
            _outcome("candidate-AAA", Decimal("-4")),
            _outcome("candidate-BBB", Decimal("8")),
            _outcome("candidate-CCC", Decimal("-7")),
        ),
    )

    assert any(
        item.reference_state is ReferenceMarketState.BEARISH_TREND
        for item in report.reference_comparison
    )
    assert report.transitions
    assert report.episodes
    assert report.reference_quality.sample_count == 3


def test_negative_regime_value_add_and_setup_regime_grouping() -> None:
    report = MarketRegimeAuditEngine().analyze(
        records=(
            _record(
                "A",
                score=Decimal("90"),
                regime="BULL",
                forward_hint="loss",
                regime_adjustment=Decimal("40"),
            ),
            _record(
                "B",
                score=Decimal("88"),
                regime="BULL",
                forward_hint="loss",
                regime_adjustment=Decimal("40"),
            ),
            _record(
                "C",
                score=Decimal("40"),
                regime="BEAR",
                forward_hint="win",
                regime_adjustment=Decimal("-40"),
            ),
            _record(
                "D",
                score=Decimal("38"),
                regime="BEAR",
                forward_hint="win",
                regime_adjustment=Decimal("-40"),
            ),
        ),
        outcomes=(
            _outcome("candidate-A", Decimal("-4")),
            _outcome("candidate-B", Decimal("-5")),
            _outcome("candidate-C", Decimal("7")),
            _outcome("candidate-D", Decimal("8")),
        ),
    )

    assert any(
        item.value_add is not None and item.value_add < Decimal("0")
        for item in report.intervention_metrics
    )
    assert report.setup_regime_interactions
    assert (
        RegimeAuditConclusion.REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY
        in report.decision.secondary_conclusions
        or report.decision.primary_conclusion
        is RegimeAuditConclusion.REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY
    )


def test_retracement_regime_interaction_and_insufficient_sample_conclusion() -> None:
    report = MarketRegimeAuditEngine(MarketRegimeAuditConfig(minimum_sample=3)).analyze(
        records=(
            _record("A", retracement=Decimal("90")),
            _record("B", retracement=Decimal("80")),
            _record("C", retracement=Decimal("20")),
            _record("D", retracement=Decimal("10")),
        ),
        outcomes=(
            _outcome("candidate-A", Decimal("-6")),
            _outcome("candidate-B", Decimal("-4")),
            _outcome("candidate-C", Decimal("5")),
            _outcome("candidate-D", Decimal("8")),
        ),
    )
    insufficient = MarketRegimeAuditEngine().analyze(records=(), outcomes=())

    assert any(
        item.finding is RetracementRegimeFinding.RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED
        for item in report.retracement_interactions
    )
    assert (
        insufficient.decision.primary_conclusion
        is RegimeAuditConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_CONCLUSION
    )


def test_exports_and_cli_rendering(tmp_path, monkeypatch) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records(_records())
    ledger.upsert_outcomes(_outcomes())
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )
    report = MarketRegimeAuditEngine().analyze(
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    json_path = tmp_path / "regime.json"
    csv_path = tmp_path / "regime.csv"

    export_market_regime_audit_json(report, json_path)
    export_market_regime_audit_csv(report, csv_path)
    rendered = "\n".join(render_market_regime_audit(report))
    grouped = "\n".join(group_market_regime_audit(report, group_by="intervention"))
    cli = CliRunner().invoke(app, ["replay", "market-regime-audit"])
    lineage = CliRunner().invoke(app, ["replay", "regime-lineage"])

    assert json.loads(json_path.read_text(encoding="utf-8"))["candidate_count"] == 4
    assert "candidate_id" in csv_path.read_text(encoding="utf-8")
    assert "Market Regime Classifier and Intervention Audit" in rendered
    assert "Regime Intervention" in grouped
    assert cli.exit_code == 0
    assert "Primary Conclusion" in cli.stdout
    assert lineage.exit_code == 0
    assert "Regime Lineage" in lineage.stdout


def _records() -> tuple[CandidateDecisionRecord, ...]:
    return (
        _record("A", regime="NEUTRAL", benchmark=Decimal("-5"), day=1),
        _record("B", regime="NEUTRAL", benchmark=Decimal("5"), day=2),
        _record("C", regime="BULL", benchmark=Decimal("6"), day=3),
        _record("D", regime="BEAR", benchmark=Decimal("-6"), day=4),
    )


def _outcomes() -> tuple[CandidateForwardOutcome, ...]:
    return (
        _outcome("candidate-A", Decimal("-4")),
        _outcome("candidate-B", Decimal("6")),
        _outcome("candidate-C", Decimal("7")),
        _outcome("candidate-D", Decimal("-5")),
    )


def _record(
    symbol: str,
    *,
    regime: str | None = "NEUTRAL",
    score: Decimal = Decimal("75"),
    benchmark: Decimal = Decimal("1"),
    retracement: Decimal = Decimal("50"),
    day: int = 1,
    data_quality: str = "COMPLETE",
    forward_hint: str = "win",
    regime_adjustment: Decimal | None = None,
) -> CandidateDecisionRecord:
    trend = Decimal("85") if forward_hint == "win" else Decimal("30")
    indicator_scores = {
        "trend": str(trend),
        "price": str(trend),
        "volume": "60",
        "retracement": str(retracement),
        "benchmark-return": str(benchmark),
    }
    if regime_adjustment is not None:
        indicator_scores["regime-adjustment"] = str(regime_adjustment)
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, day),
        symbol=symbol,
        final_verdict="BUY" if score >= Decimal("70") else "AVOID",
        capital_action="BUY" if score >= Decimal("70") else "AVOID",
        approved_for_deployment=score >= Decimal("85"),
        rejection_reasons=() if score >= Decimal("85") else ("test rejection",),
        setup_type="MOMENTUM CONTINUATION",
        market_regime=regime,
        long_trade_permission=True,
        strategy_score=score,
        confidence="HIGH",
        data_quality=data_quality,
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("102"),
        risk_stop=Decimal("95"),
        target_1=Decimal("112"),
        target_2=Decimal("125"),
        target_3=Decimal("140"),
        trailing_stop_plan="Trail using 2 x ATR.",
        expected_holding_period="20d",
        indicators_active=("trend", "price", "retracement"),
        indicator_scores=indicator_scores,
        evidence_layers=("Price/Volume",),
        explanation="Synthetic replay candidate.",
        created_at=datetime(2026, 1, day, tzinfo=UTC),
        sector="IT",
    )


def _outcome(candidate_id: str, forward_return: Decimal) -> CandidateForwardOutcome:
    won = forward_return > Decimal("0")
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.replace("candidate-", ""),
        evaluated_at=datetime(2026, 1, 22, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("120") if won else Decimal("104"),
                forward_low=Decimal("98") if won else Decimal("90"),
                forward_close=Decimal("100") + forward_return,
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=Decimal("12") if won else Decimal("2"),
                max_adverse_excursion_pct=Decimal("-2") if won else Decimal("-10"),
                target_1_touched=won,
                risk_stop_touched=not won,
                outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON
                if won
                else CandidateOutcomeLabel.WOULD_HAVE_LOST,
            ),
        ),
    )
