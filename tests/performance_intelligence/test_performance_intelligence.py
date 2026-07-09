from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from typer.testing import CliRunner

from alpha.cli import app
from alpha.performance_intelligence import (
    PerformanceIntelligenceService,
    PerformanceReportBuilder,
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationLedgerRepository,
    RecommendationOutcome,
    RecommendationOutcomeEvaluator,
    RecommendationOutcomeStatus,
)
from alpha.performance_intelligence.reporting import render_performance_report
from alpha.recommendation_intelligence.models import OHLCVBar


def test_recommendation_ledger_insert_and_idempotency(tmp_path) -> None:
    repository = RecommendationLedgerRepository(tmp_path / "ledger.json")
    entry = _entry("AAA")

    assert repository.save_entry(entry) is True
    assert repository.save_entry(entry) is False

    entries = repository.load_entries()
    assert len(entries) == 1
    assert entries[0].symbol == "AAA"


def test_pending_to_active_transition() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=5)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (_bar(1, high="101", low="99", close="100"),),
    )

    assert outcome.status is RecommendationOutcomeStatus.ACTIVE
    assert outcome.entry_triggered is True
    assert outcome.entry_price == Decimal("101.00")


def test_active_to_target_exit() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=5)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (
            _bar(1, high="101", low="99", close="100"),
            _bar(2, high="112", low="102", close="111"),
        ),
    )

    assert outcome.status is RecommendationOutcomeStatus.EXITED
    assert outcome.exit_reason is RecommendationExitReason.TARGET_1
    assert outcome.target_1_hit is True
    assert outcome.realized_r_multiple == Decimal("2.20")


def test_active_to_stop_exit() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=5)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (
            _bar(1, high="101", low="99", close="100"),
            _bar(2, high="103", low="94", close="95"),
        ),
    )

    assert outcome.status is RecommendationOutcomeStatus.EXITED
    assert outcome.exit_reason is RecommendationExitReason.STOP_LOSS
    assert outcome.stop_hit is True
    assert outcome.realized_r_multiple == Decimal("-1.00")


def test_not_triggered_expiry() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=2)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (
            _bar(1, high="100", low="97", close="99"),
            _bar(2, high="100", low="97", close="99"),
        ),
    )

    assert outcome.status is RecommendationOutcomeStatus.NOT_TRIGGERED
    assert outcome.exit_reason is RecommendationExitReason.NOT_TRIGGERED


def test_mfe_and_mae_are_calculated() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=5)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (
            _bar(1, high="101", low="99", close="100"),
            _bar(2, high="109", low="97", close="108"),
        ),
    )

    assert outcome.status is RecommendationOutcomeStatus.ACTIVE
    assert outcome.maximum_favorable_excursion == Decimal("8.00")
    assert outcome.maximum_adverse_excursion == Decimal("-4.00")


def test_r_multiple_calculation() -> None:
    evaluator = RecommendationOutcomeEvaluator(default_expiry_bars=5)
    outcome = evaluator.evaluate(
        _entry("AAA"),
        (
            _bar(1, high="101", low="99", close="100"),
            _bar(2, high="117", low="102", close="116"),
        ),
    )

    assert outcome.exit_reason is RecommendationExitReason.TARGET_2
    assert outcome.realized_r_multiple == Decimal("3.20")


def test_insufficient_sample_reporting() -> None:
    report = PerformanceReportBuilder(minimum_sample_size=2).build(
        entries=(_entry("AAA"),),
        outcomes=(
            RecommendationOutcome(
                recommendation_id="rec-AAA",
                symbol="AAA",
                status=RecommendationOutcomeStatus.EXITED,
                entry_triggered=True,
                realized_r_multiple=Decimal("1"),
                realized_percent_return=Decimal("5"),
            ),
        ),
    )

    lines = render_performance_report(report)

    assert "Sample Size: 1 completed trades; insufficient data" in "\n".join(lines)


def test_performance_report_aggregation() -> None:
    report = PerformanceReportBuilder(minimum_sample_size=1).build(
        entries=(_entry("AAA"), _entry("BBB", verdict="SELL", sector="BANKS")),
        outcomes=(
            _outcome("rec-AAA", "AAA", Decimal("1.00"), target_1=True),
            _outcome("rec-BBB", "BBB", Decimal("-1.00"), stop=True),
        ),
    )

    assert report.metrics.completed_trades == 2
    assert report.metrics.win_rate == Decimal("0.5000")
    assert report.metrics.profit_factor == Decimal("1.0000")
    assert "verdict:BUY" in report.breakdowns
    assert "sector:BANKS" in report.breakdowns


def test_cli_update_output(tmp_path) -> None:
    repository = RecommendationLedgerRepository(tmp_path / "ledger.json")
    repository.save_entry(_entry("AAA"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["performance", "update", "--ledger", str(tmp_path / "ledger.json")],
    )

    assert result.exit_code == 0
    assert "Performance Update Summary" in result.stdout
    assert "Recommendations Checked: 1" in result.stdout
    assert "Missing Data Count: 1" in result.stdout


def test_cli_report_output(tmp_path) -> None:
    repository = RecommendationLedgerRepository(tmp_path / "ledger.json")
    repository.save_entry(_entry("AAA"))
    repository.upsert_outcome(
        _outcome("rec-AAA", "AAA", Decimal("1.00"), target_1=True)
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["performance", "report", "--ledger", str(tmp_path / "ledger.json")],
    )

    assert result.exit_code == 0
    assert "Performance Intelligence Report" in result.stdout
    assert "Total Recommendations: 1" in result.stdout
    assert "Completed Trades: 1" in result.stdout
    assert "Breakdowns:" in result.stdout


def test_repeated_cli_run_does_not_duplicate_ledger_rows(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.json"
    runner = CliRunner()
    command = [
        "intelligence",
        "--demo",
        "--date",
        "2026-01-30",
    ]
    env = {"ALPHA_RECOMMENDATION_LEDGER": str(ledger_path)}

    first = runner.invoke(app, command, env=env)
    second = runner.invoke(app, command, env=env)

    assert first.exit_code == 0
    assert second.exit_code == 0
    entries = RecommendationLedgerRepository(ledger_path).load_entries()
    assert [entry.symbol for entry in entries] == ["BEL", "HAL", "LT"]


def test_service_update_uses_available_future_bars(tmp_path) -> None:
    repository = RecommendationLedgerRepository(tmp_path / "ledger.json")
    repository.save_entry(_entry("AAA"))
    service = PerformanceIntelligenceService(
        repository=repository,
        future_bars_by_symbol={
            "AAA": (
                _bar(1, high="101", low="99", close="100"),
                _bar(2, high="112", low="102", close="111"),
            )
        },
        evaluator=RecommendationOutcomeEvaluator(default_expiry_bars=5),
    )

    summary = service.update()
    outcome = repository.load_outcomes()[0]

    assert summary.newly_entered == 1
    assert summary.newly_exited == 1
    assert outcome.status is RecommendationOutcomeStatus.EXITED


def _entry(
    symbol: str,
    *,
    verdict: str = "BUY",
    sector: str = "IT",
) -> RecommendationLedgerEntry:
    return RecommendationLedgerEntry(
        recommendation_id=f"rec-{symbol}",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        symbol=symbol,
        final_verdict=verdict,
        confidence="HIGH",
        score=Decimal("82"),
        setup_type="MOMENTUM_CONTINUATION",
        setup_state="ENTRY_READY",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("101"),
        stop_loss=Decimal("96"),
        target_1=Decimal("112"),
        target_2=Decimal("117"),
        target_3=Decimal("121"),
        trailing_stop_strategy=(
            "After entry, trail stop at 2 x ATR below highest close."
        ),
        holding_period="2-4 weeks",
        market_regime="BULLISH",
        sector=sector,
        key_indicator_snapshot={"price_score": "0.80"},
        statistical_edge_snapshot={"sample_size": "12"},
        data_completeness_snapshot={"data_quality": "complete"},
        source_run_id="run-1",
    )


def _bar(offset: int, *, high: str, low: str, close: str) -> OHLCVBar:
    observed_on = date(2026, 1, 1) + timedelta(days=offset)
    return OHLCVBar(
        observed_on=observed_on,
        open_price=Decimal(low),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100000"),
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
        exit_date=date(2026, 1, 3),
        exit_price=Decimal("112") if r_multiple > 0 else Decimal("96"),
        exit_reason=RecommendationExitReason.TARGET_1
        if r_multiple > 0
        else RecommendationExitReason.STOP_LOSS,
        stop_hit=stop,
        target_1_hit=target_1,
        realized_r_multiple=r_multiple,
        realized_percent_return=Decimal("5") if r_multiple > 0 else Decimal("-2"),
        holding_period_bars=2,
        holding_period_days=1,
    )
