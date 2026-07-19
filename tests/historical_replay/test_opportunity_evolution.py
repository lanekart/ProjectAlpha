from __future__ import annotations

from datetime import date, timedelta

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import (
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    EntryMarker,
    OpportunityLifecycleState,
    TriggerRuleName,
    build_opportunity_evolution_report,
    evaluate_trigger_policy,
    export_opportunity_evolution_csv,
    export_opportunity_evolution_json,
    group_opportunity_report,
    pareto_trigger_frontier,
    reconstruct_opportunity_paths,
    render_opportunity_evolution_report,
    trigger_policies,
)


def _definition() -> DirectionalOutcomeDefinition:
    return DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )


def _observation(
    symbol: str,
    day: date,
    *,
    score: float,
    timing: str,
    forward_return: float,
    setup: str = "MOMENTUM_CONTINUATION",
    regime: str = "BULL",
    volume: float = 0.70,
    trade_plan: float = 0.60,
    stop: float = 0.04,
    price: float = 100.0,
) -> DirectionalObservation:
    return DirectionalObservation(
        symbol=symbol,
        observed_at=day,
        horizon_days=20,
        forward_return=forward_return,
        max_favorable_excursion=max(forward_return, 0.01) + 0.05,
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
        sector="TEST",
        source="unit-test",
        feature_values=(
            ("breakout_confirmation", score),
            ("price_volume", score),
            ("relative_strength", score),
            ("setup_quality", score),
            ("support", price * 0.96),
            ("target", price * 1.08),
            ("trade_plan", trade_plan),
            ("volume", volume),
        ),
    )


def test_identity_grouping_resets_on_setup_regime_gap_and_invalidation() -> None:
    start = date(2024, 1, 1)
    rows = (
        _observation("AAA", start, score=0.42, timing="FORMING", forward_return=0.05),
        _observation(
            "AAA",
            start + timedelta(days=5),
            score=0.62,
            timing="PREFERRED",
            forward_return=0.06,
        ),
        _observation(
            "AAA",
            start + timedelta(days=7),
            score=0.62,
            timing="PREFERRED",
            forward_return=0.06,
            setup="BREAKOUT",
        ),
        _observation(
            "AAA",
            start + timedelta(days=14),
            score=0.62,
            timing="PREFERRED",
            forward_return=0.06,
            setup="BREAKOUT",
            regime="BEAR",
        ),
        _observation(
            "AAA",
            start + timedelta(days=70),
            score=0.62,
            timing="PREFERRED",
            forward_return=0.06,
            setup="BREAKOUT",
            regime="BEAR",
        ),
        _observation(
            "AAA",
            start + timedelta(days=75),
            score=0.10,
            timing="INVALID",
            forward_return=-0.05,
            setup="BREAKOUT",
            regime="BEAR",
        ),
        _observation(
            "AAA",
            start + timedelta(days=76),
            score=0.62,
            timing="PREFERRED",
            forward_return=0.06,
            setup="BREAKOUT",
            regime="BEAR",
        ),
    )

    paths = reconstruct_opportunity_paths(rows, definition=_definition())
    first_path = next(
        path for path in paths if path.identity.first_detection_date == start
    )

    assert len(paths) == 5
    assert first_path.observation_count == 2
    assert first_path.identity.opportunity_id.startswith(
        "AAA-MOMENTUM-CONTINUATION-BUY-2024-01-01"
    )


def test_lifecycle_transitions_and_hindsight_marker_are_diagnostic_only() -> None:
    start = date(2024, 2, 1)
    rows = (
        _observation(
            "BBB",
            start,
            score=0.25,
            timing="FORMING",
            forward_return=0.03,
            volume=0.20,
            trade_plan=0.20,
            stop=0.12,
        ),
        _observation(
            "BBB",
            start + timedelta(days=1),
            score=0.52,
            timing="EARLY",
            forward_return=0.07,
        ),
        _observation(
            "BBB",
            start + timedelta(days=2),
            score=0.72,
            timing="CONFIRMATION",
            forward_return=0.04,
        ),
    )

    path = reconstruct_opportunity_paths(rows, definition=_definition())[0]
    states = [item.lifecycle_state for item in path.observations]

    assert states == [
        OpportunityLifecycleState.DETECTED,
        OpportunityLifecycleState.TRADEABLE_EARLY,
        OpportunityLifecycleState.CONFIRMED,
    ]
    assert len(path.transitions) == 2
    best_entries = [
        item
        for item in path.entry_outcomes
        if item.marker is EntryMarker.HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY
    ]
    assert len(best_entries) == 1
    assert best_entries[0].diagnostic_only is True


def test_trigger_policy_one_signal_per_opportunity_with_inflation() -> None:
    start = date(2024, 3, 1)
    path = reconstruct_opportunity_paths(
        (
            _observation(
                "CCC",
                start,
                score=0.80,
                timing="CONFIRMATION",
                forward_return=0.05,
            ),
            _observation(
                "CCC",
                start + timedelta(days=1),
                score=0.82,
                timing="CONFIRMATION",
                forward_return=0.04,
            ),
        ),
        definition=_definition(),
    )[0]
    policy = next(
        item
        for item in trigger_policies()
        if item.name is TriggerRuleName.CURRENT_PRODUCTION_ENTRY
    )

    evaluation = evaluate_trigger_policy((path,), policy, definition=_definition())

    assert evaluation.triggered_opportunities == 1
    assert evaluation.precision == 1.0
    assert evaluation.signal_inflation_factor == 2.0


def test_scores_are_separated_and_maturation_deltas_are_point_in_time() -> None:
    start = date(2024, 4, 1)
    path = reconstruct_opportunity_paths(
        (
            _observation(
                "DDD",
                start,
                score=0.70,
                timing="FORMING",
                forward_return=0.05,
                trade_plan=0.20,
            ),
            _observation(
                "DDD",
                start + timedelta(days=1),
                score=0.72,
                timing="PREFERRED",
                forward_return=0.06,
                trade_plan=0.80,
            ),
        ),
        definition=_definition(),
    )[0]
    latest = path.observations[-1]

    assert latest.opportunity_quality_score != latest.entry_trigger_score
    assert any(
        feature.one_observation_delta is not None and feature.point_in_time is True
        for feature in latest.source_features
    )


def test_frontier_report_taxonomies_and_grouping_are_deterministic() -> None:
    report = build_opportunity_evolution_report(
        (
            _observation(
                "EEE",
                date(2024, 5, 1),
                score=0.80,
                timing="EARLY",
                forward_return=-0.04,
            ),
            _observation(
                "FFF",
                date(2024, 5, 2),
                score=0.82,
                timing="CONFIRMATION",
                forward_return=0.05,
            ),
            _observation(
                "GGG",
                date(2024, 5, 3),
                score=0.30,
                timing="FORMING",
                forward_return=0.05,
            ),
        ),
        definition=_definition(),
    )

    frontier = pareto_trigger_frontier(report.trigger_frontier)
    lines = render_opportunity_evolution_report(report)

    assert frontier
    assert report.current_policy.policy.name is TriggerRuleName.CURRENT_PRODUCTION_ENTRY
    assert report.best_rule.policy.name in {item.policy.name for item in frontier}
    assert report.early_entry_failures
    assert report.current_policy.opportunity_level_precision is not None
    assert report.current_policy.observation_level_precision is not None
    assert "PRODUCTION_INFLUENCE=false" in lines
    assert any(
        "MOMENTUM_CONTINUATION" in line
        for line in group_opportunity_report(report, "setup")
    )


def test_export_json_and_csv(tmp_path) -> None:
    report = build_opportunity_evolution_report(
        (
            _observation(
                "HHH",
                date(2024, 6, 1),
                score=0.80,
                timing="CONFIRMATION",
                forward_return=0.05,
            ),
        ),
        definition=_definition(),
    )
    json_path = tmp_path / "opportunities.json"
    csv_path = tmp_path / "opportunities.csv"

    export_opportunity_evolution_json(report, json_path)
    export_opportunity_evolution_csv(report, csv_path)

    assert '"unique_opportunities": 1' in json_path.read_text()
    assert "opportunity_id,symbol" in csv_path.read_text()


def test_cli_opportunity_evolution_text_and_filters() -> None:
    result = CliRunner().invoke(
        app,
        [
            "replay",
            "opportunity-evolution",
            "--trigger",
            "full-stack-plus-timing",
        ],
    )

    assert result.exit_code == 0
    assert "Opportunity Evolution Intelligence" in result.stdout
    assert "Best Trigger Rule: FULL_STACK_PLUS_TIMING" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_cli_opportunity_paths_group_by_year() -> None:
    result = CliRunner().invoke(
        app,
        ["replay", "opportunity-paths", "--group-by", "year"],
    )

    assert result.exit_code == 0
    assert "Opportunity Paths Grouped By year:" in result.stdout
    assert "- " in result.stdout
