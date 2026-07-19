from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.cli import app
from alpha.learning_intelligence import (
    AdaptiveLearningEngine,
    EvidenceStrength,
    SetupFingerprint,
    fingerprint_from_ledger_entry,
    fingerprint_from_recommendation,
)
from alpha.performance_intelligence import (
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationLedgerRepository,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)


def test_fingerprint_key_stability() -> None:
    fingerprint = _fingerprint()

    assert fingerprint.key == _fingerprint().key
    assert "setup=MOMENTUM" in fingerprint.key


def test_fingerprint_extraction_from_ledger_entry() -> None:
    fingerprint = fingerprint_from_ledger_entry(_entry("AAA"))

    assert fingerprint.final_verdict == "BUY"
    assert fingerprint.trend_regime == "STRONG_UPTREND"
    assert fingerprint.volume_regime == "STRONG"
    assert fingerprint.dma_alignment == "BULLISH"


def test_fingerprint_extraction_from_recommendation() -> None:
    recommendation = (
        IntelligenceApplicationService()
        .run(observed_on=date(2026, 1, 30))
        .recommendations[0]
    )

    fingerprint = fingerprint_from_recommendation(
        recommendation,
        market_regime="BULLISH",
    )

    assert fingerprint.final_verdict == recommendation.final_signal
    assert fingerprint.setup_type == recommendation.setup_name
    assert fingerprint.market_regime == "BULLISH"


def test_aggregation_by_fingerprint() -> None:
    report = AdaptiveLearningEngine().build_report(
        entries=(_entry("AAA"), _entry("BBB")),
        outcomes=(
            _outcome("rec-AAA", "AAA", Decimal("1")),
            _outcome("rec-BBB", "BBB", Decimal("-1")),
        ),
    )

    stat = report.fingerprint_statistics[0]
    assert stat.sample_count == 2
    assert stat.completed_trade_count == 2
    assert stat.win_count == 1
    assert stat.loss_count == 1


def test_insufficient_evidence_behavior() -> None:
    report = AdaptiveLearningEngine().build_report(
        entries=(_entry("AAA"),),
        outcomes=(_outcome("rec-AAA", "AAA", Decimal("1")),),
    )

    stat = report.fingerprint_statistics[0]
    assert stat.evidence_strength is EvidenceStrength.INSUFFICIENT
    assert "insufficient evidence" in report.insufficient_sample_warnings[0]


def test_bayesian_update_with_no_evidence() -> None:
    stat = (
        AdaptiveLearningEngine()
        .build_report(
            entries=(_entry("AAA"),),
            outcomes=(),
        )
        .fingerprint_statistics[0]
    )

    calibration = AdaptiveLearningEngine().bayesian_calibration(stat)

    assert calibration.prior_win_probability == Decimal("0.5000")
    assert calibration.posterior_win_probability == Decimal("0.5000")
    assert calibration.evidence_strength is EvidenceStrength.INSUFFICIENT


def test_bayesian_update_with_winning_evidence() -> None:
    stat = _report_with_outcomes(
        tuple(
            _outcome(f"rec-A{index}", f"A{index}", Decimal("1")) for index in range(6)
        )
    ).fingerprint_statistics[0]

    calibration = AdaptiveLearningEngine().bayesian_calibration(stat)

    assert calibration.posterior_win_probability > Decimal("0.50")
    assert calibration.evidence_strength is EvidenceStrength.WEAK


def test_bayesian_update_with_losing_evidence() -> None:
    stat = _report_with_outcomes(
        tuple(
            _outcome(f"rec-A{index}", f"A{index}", Decimal("-1")) for index in range(6)
        )
    ).fingerprint_statistics[0]

    calibration = AdaptiveLearningEngine().bayesian_calibration(stat)

    assert calibration.posterior_win_probability < Decimal("0.50")


def test_confidence_not_inflated_on_weak_evidence() -> None:
    engine = AdaptiveLearningEngine()
    stat = _report_with_outcomes(
        tuple(
            _outcome(f"rec-A{index}", f"A{index}", Decimal("1")) for index in range(6)
        )
    ).fingerprint_statistics[0]

    calibration = engine.recalibrate_confidence(
        base_confidence="MEDIUM",
        statistics=stat,
        bayesian=engine.bayesian_calibration(stat),
    )

    assert calibration.adjusted_confidence == "MEDIUM"
    assert "weak" in calibration.adjustment_reason


def test_confidence_reduced_on_strong_negative_evidence() -> None:
    engine = AdaptiveLearningEngine()
    stat = _report_with_outcomes(
        tuple(
            _outcome(f"rec-A{index}", f"A{index}", Decimal("-1")) for index in range(30)
        )
    ).fingerprint_statistics[0]

    calibration = engine.recalibrate_confidence(
        base_confidence="HIGH",
        statistics=stat,
        bayesian=engine.bayesian_calibration(stat),
    )

    assert calibration.adjusted_confidence == "MEDIUM"
    assert "strong negative" in calibration.adjustment_reason


def test_regime_sector_and_confidence_bucket_aggregation() -> None:
    report = AdaptiveLearningEngine().build_report(
        entries=(
            _entry("AAA", sector="IT", regime="BULLISH", confidence="HIGH"),
            _entry("BBB", sector="BANKS", regime="BEARISH", confidence="LOW"),
        ),
        outcomes=(
            _outcome("rec-AAA", "AAA", Decimal("1")),
            _outcome("rec-BBB", "BBB", Decimal("-1")),
        ),
    )

    assert "BULLISH" in report.regime_statistics
    assert "BANKS" in report.sector_statistics
    assert "HIGH" in report.confidence_statistics


def test_feature_contribution_ranking() -> None:
    report = AdaptiveLearningEngine().build_report(
        entries=(_entry("AAA"), _entry("BBB", sector="BANKS")),
        outcomes=(
            _outcome("rec-AAA", "AAA", Decimal("2"), target_1=True),
            _outcome("rec-BBB", "BBB", Decimal("-1"), stop=True),
        ),
    )

    assert report.feature_contributions
    assert report.feature_contributions[0].average_expectancy is not None


def test_cli_learning_report_output(tmp_path) -> None:
    ledger = _write_ledger(tmp_path)

    result = CliRunner().invoke(
        app,
        ["learning", "report", "--ledger", str(ledger)],
    )

    assert result.exit_code == 0
    assert "Adaptive Learning Report" in result.stdout
    assert "Confidence Calibration Table" in result.stdout
    assert "Feature Contribution Summary" in result.stdout


def test_cli_learning_explain_output(tmp_path) -> None:
    ledger = _write_ledger(tmp_path)

    result = CliRunner().invoke(
        app,
        ["learning", "explain", "--symbol", "AAA", "--ledger", str(ledger)],
    )

    assert result.exit_code == 0
    assert "Adaptive Learning Explain: AAA" in result.stdout
    assert "Fingerprint:" in result.stdout
    assert "Posterior Probability:" in result.stdout
    assert "Adjusted Confidence:" in result.stdout


def test_recommendation_output_includes_adaptive_evidence(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["intelligence", "--demo", "--date", "2026-01-30"],
        env={"ALPHA_RECOMMENDATION_LEDGER": str(tmp_path / "ledger.json")},
    )

    assert result.exit_code == 0
    assert "Adaptive Evidence:" in result.stdout


def _report_with_outcomes(outcomes: tuple[RecommendationOutcome, ...]):
    entries = tuple(
        _entry(outcome.symbol, recommendation_id=outcome.recommendation_id)
        for outcome in outcomes
    )
    return AdaptiveLearningEngine().build_report(entries=entries, outcomes=outcomes)


def _fingerprint() -> SetupFingerprint:
    return SetupFingerprint(
        final_verdict="BUY",
        setup_type="MOMENTUM",
        setup_state="ENTRY_READY",
        market_regime="BULLISH",
        sector="IT",
        trend_regime="UP",
        volume_regime="STRONG",
        volatility_regime="NORMAL",
        relative_strength_regime="STRONG",
        candle_pattern="BULLISH_ENGULFING",
        breakout_retracement_state="BREAKOUT",
        dma_alignment="BULLISH",
        data_completeness_level="COMPLETE",
    )


def _entry(
    symbol: str,
    *,
    recommendation_id: str | None = None,
    sector: str = "IT",
    regime: str = "BULLISH",
    confidence: str = "HIGH",
) -> RecommendationLedgerEntry:
    return RecommendationLedgerEntry(
        recommendation_id=recommendation_id or f"rec-{symbol}",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        symbol=symbol,
        final_verdict="BUY",
        confidence=confidence,
        score=Decimal("82"),
        setup_type="MOMENTUM",
        setup_state="ENTRY_READY",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("101"),
        stop_loss=Decimal("96"),
        target_1=Decimal("112"),
        target_2=Decimal("117"),
        target_3=Decimal("121"),
        trailing_stop_strategy="2 x ATR trail",
        holding_period="2-4 weeks",
        market_regime=regime,
        sector=sector,
        key_indicator_snapshot={
            "price_trend": "STRONG_UPTREND",
            "price_breakout": "BREAKOUT",
            "retracement_state": "HEALTHY",
            "volume_score": "0.80",
            "relative_volume": "1.30",
            "atr": "2.50",
            "dma_20": "120",
            "dma_50": "110",
            "dma_200": "100",
            "candle_pattern": "BULLISH_ENGULFING",
        },
        statistical_edge_snapshot={"sample_size": "12"},
        data_completeness_snapshot={"data_quality": "complete"},
        source_run_id="run-1",
    )


def _outcome(
    recommendation_id: str,
    symbol: str,
    r_multiple: Decimal,
    *,
    target_1: bool = False,
    stop: bool = False,
) -> RecommendationOutcome:
    return RecommendationOutcome(
        recommendation_id=recommendation_id,
        symbol=symbol,
        status=RecommendationOutcomeStatus.EXITED,
        entry_triggered=True,
        entry_date=date(2026, 1, 2),
        entry_price=Decimal("101"),
        exit_date=date(2026, 1, 5),
        exit_price=Decimal("112") if r_multiple > 0 else Decimal("96"),
        exit_reason=RecommendationExitReason.TARGET_1
        if r_multiple > 0
        else RecommendationExitReason.STOP_LOSS,
        stop_hit=stop,
        target_1_hit=target_1,
        realized_r_multiple=r_multiple,
        realized_percent_return=Decimal("5") if r_multiple > 0 else Decimal("-2"),
        holding_period_bars=3,
        holding_period_days=3,
    )


def _write_ledger(tmp_path) -> str:
    ledger = tmp_path / "ledger.json"
    repository = RecommendationLedgerRepository(ledger)
    repository.save_entries((_entry("AAA"), _entry("BBB", sector="BANKS")))
    repository.upsert_outcomes(
        (
            _outcome("rec-AAA", "AAA", Decimal("1"), target_1=True),
            _outcome("rec-BBB", "BBB", Decimal("-1"), stop=True),
        )
    )
    return str(ledger)
