from __future__ import annotations

from datetime import date, timedelta

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import DirectionalObservation
from alpha.historical_replay.confirmation_intelligence import (
    CancellationReason,
    ConfirmationRuleName,
    DirectionFailureClassification,
    Preventability,
    RetestState,
    TriggerFailureCause,
    build_confirmation_intelligence_report,
    export_confirmation_intelligence_csv,
    export_confirmation_intelligence_json,
    group_confirmation_report,
    render_confirmation_intelligence_report,
)


def _observation(
    symbol: str,
    day: date,
    *,
    score: float,
    timing: str,
    forward_return: float,
    volume: float = 0.70,
    rs: float = 0.70,
    support: float = 96.0,
    price: float = 100.0,
    setup: str = "MOMENTUM_BREAKOUT",
    regime: str = "BULL",
    stop: float = 0.04,
    trade_plan: float = 0.70,
    mfe: float | None = None,
) -> DirectionalObservation:
    return DirectionalObservation(
        symbol=symbol,
        observed_at=day,
        horizon_days=20,
        forward_return=forward_return,
        max_favorable_excursion=mfe
        if mfe is not None
        else max(forward_return, 0.01) + 0.04,
        max_adverse_excursion=-stop,
        recommendation_score=score,
        price_component=score,
        setup_quality=score,
        entry_timing=timing,
        regime=regime,
        setup_type=setup,
        trade_plan_quality=trade_plan,
        stop_distance_pct=stop,
        expected_value=forward_return,
        confidence=score,
        completed=True,
        upside_barrier_day=2 if forward_return > 0.02 else None,
        downside_barrier_day=2 if forward_return < -0.02 else None,
        sector="TEST_SECTOR",
        source="unit-test",
        feature_values=(
            ("breakout_confirmation", score),
            ("liquidity", volume),
            ("price", price),
            ("price_volume", score),
            ("relative_strength", rs),
            ("support", support),
            ("target", price * 1.08),
            ("trade_plan", trade_plan),
            ("volume", volume),
        ),
    )


def _rows() -> tuple[DirectionalObservation, ...]:
    start = date(2024, 1, 1)
    return (
        _observation(
            "AAA",
            start,
            score=0.72,
            timing="CONFIRMATION",
            forward_return=0.06,
        ),
        _observation(
            "BBB",
            start + timedelta(days=1),
            score=0.70,
            timing="PREFERRED",
            forward_return=-0.05,
            volume=0.25,
            rs=0.35,
        ),
        _observation(
            "CCC",
            start + timedelta(days=2),
            score=0.74,
            timing="PREFERRED",
            forward_return=-0.04,
            volume=0.72,
            rs=0.72,
        ),
        _observation(
            "CCC",
            start + timedelta(days=3),
            score=0.45,
            timing="FORMING",
            forward_return=-0.04,
            volume=0.25,
            rs=0.25,
        ),
        _observation(
            "DDD",
            start + timedelta(days=4),
            score=0.68,
            timing="PREFERRED",
            forward_return=0.05,
            volume=0.40,
            support=98.5,
        ),
        _observation(
            "EEE",
            start + timedelta(days=5),
            score=0.70,
            timing="PREFERRED",
            forward_return=-0.06,
            regime="BEAR",
            support=102.0,
        ),
        _observation(
            "FFF",
            start + timedelta(days=6),
            score=0.74,
            timing="PREFERRED",
            forward_return=-0.05,
            volume=0.72,
            rs=0.72,
            mfe=0.01,
        ),
    )


def test_frozen_baseline_reproduction_and_main_report() -> None:
    report = build_confirmation_intelligence_report(_rows())
    lines = render_confirmation_intelligence_report(report)

    assert report.baseline.rule is ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING
    assert report.baseline.triggered_opportunities == 6
    assert report.baseline.successes == 2
    assert report.baseline.failures == 4
    assert report.baseline.precision == 2 / 6
    assert report.production_influence is False
    assert "PRODUCTION_INFLUENCE=false" in lines


def test_failure_taxonomy_preventability_grouping_and_direction() -> None:
    report = build_confirmation_intelligence_report(_rows())

    all_causes = {
        cause
        for item in report.failures
        for cause in (item.primary_cause, *item.secondary_causes)
    }
    assert all_causes >= {
        TriggerFailureCause.FALSE_BREAKOUT,
        TriggerFailureCause.WEAK_RELATIVE_STRENGTH,
    }
    assert any(
        item.preventability is Preventability.PREVENTABLE_WITH_EXISTING_EVIDENCE
        for item in report.failures
    )
    assert all(item.grouping_quality.value for item in report.failures)
    assert {item.direction_failure for item in report.failures} <= set(
        DirectionFailureClassification
    )


def test_confirmation_scores_participation_retest_and_cancellation() -> None:
    report = build_confirmation_intelligence_report(_rows())
    records = {item.instrument: item for item in report.opportunity_records}
    score_names = {score.name for score in records["AAA"].confirmation_features}

    assert "OPPORTUNITY_QUALITY_SCORE" in score_names
    assert "ENTRY_TRIGGER_SCORE" in score_names
    assert "PARTICIPATION_CONFIRMATION_SCORE" in score_names
    assert "CONFIRMED_ENTRY_SCORE" in score_names
    assert records["DDD"].retest_state is RetestState.CONTROLLED_RETEST
    assert records["EEE"].retest_state is RetestState.FAILED_RETEST
    assert (
        CancellationReason.VOLUME_CONFIRMATION_LOST
        in records["CCC"].cancellation_reasons
    )


def test_frontier_ordered_addition_ablation_and_grouping() -> None:
    report = build_confirmation_intelligence_report(_rows())

    assert report.frontier
    assert report.pareto_frontier
    assert (
        report.ordered_addition[0].rule
        is ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING
    )
    assert report.ablation is not None
    assert report.top_failure_causes
    assert any(
        "FALSE_BREAKOUT" in line
        for line in group_confirmation_report(report, "failure-cause")
    )
    assert any(
        "FROZEN_FULL_STACK_PLUS_TIMING" in line
        for line in group_confirmation_report(report, "trigger")
    )


def test_exports_are_deterministic(tmp_path) -> None:
    report = build_confirmation_intelligence_report(_rows())
    json_path = tmp_path / "confirmation.json"
    csv_path = tmp_path / "confirmation.csv"

    export_confirmation_intelligence_json(report, json_path)
    export_confirmation_intelligence_csv(report, csv_path)

    assert (
        '"frozen_baseline_trigger": "FULL_STACK_PLUS_TIMING"' in json_path.read_text()
    )
    assert "opportunity_id,instrument,setup" in csv_path.read_text()


def test_cli_confirmation_intelligence_and_grouping() -> None:
    result = CliRunner().invoke(app, ["replay", "confirmation-intelligence"])

    assert result.exit_code == 0
    assert "Entry Trigger Confirmation Intelligence" in result.stdout
    assert "Frozen Baseline Trigger: FULL_STACK_PLUS_TIMING" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout

    grouped = CliRunner().invoke(
        app,
        ["replay", "trigger-failure-attribution", "--group-by", "preventability"],
    )
    assert grouped.exit_code == 0
    assert "Trigger Failure Attribution Grouped By preventability:" in grouped.stdout
