from __future__ import annotations

import json
from datetime import date

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import (
    DirectionalLabel,
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    DirectionalPolicy,
    DirectionalPolicyDirection,
    PrecisionCoverageConstraints,
    build_directional_calibration_report,
    build_policy_candidate_report,
    build_precision_coverage_report,
    calculate_directional_metrics,
    deterministic_research_observations,
    effective_sample_size,
    export_calibration_csv,
    export_frontier_csv,
    export_precision_coverage_json,
    feature_lineage_audit,
    label_barrier_first,
    label_directional_outcome,
    label_terminal_return,
    nested_walk_forward,
    pareto_frontier,
    retracement_ablation,
    setup_directional_analysis,
    wilson_interval,
)


def test_terminal_labels_buy_sell_neutral_and_unavailable() -> None:
    definition = DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.03,
        negative_return_threshold=-0.03,
    )

    assert label_terminal_return(_observation("BUY", 0.04), definition) is (
        DirectionalLabel.BUY_DIRECTIONAL
    )
    assert label_terminal_return(_observation("SELL", -0.04), definition) is (
        DirectionalLabel.SELL_DIRECTIONAL
    )
    assert label_terminal_return(_observation("NEUTRAL", 0.01), definition) is (
        DirectionalLabel.NEUTRAL
    )
    assert label_terminal_return(_observation("NA", None), definition) is (
        DirectionalLabel.UNAVAILABLE
    )


def test_symmetric_barrier_logic() -> None:
    definition = DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.BARRIER_FIRST,
        horizon_days=20,
    )

    assert (
        label_barrier_first(
            _observation("BUY", 0.05, upside_day=2, downside_day=7),
            definition,
        )
        is DirectionalLabel.BUY_DIRECTIONAL
    )
    assert (
        label_barrier_first(
            _observation("SELL", -0.05, upside_day=7, downside_day=2),
            definition,
        )
        is DirectionalLabel.SELL_DIRECTIONAL
    )
    assert (
        label_barrier_first(
            _observation("NEUTRAL", 0.0, upside_day=3, downside_day=3),
            definition,
        )
        is DirectionalLabel.NEUTRAL
    )


def test_unavailable_when_horizon_is_not_complete() -> None:
    definition = DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=60,
    )

    label = label_directional_outcome(_observation("SHORT", 0.10), definition)

    assert label is DirectionalLabel.UNAVAILABLE


def test_precision_and_economic_metrics_are_deterministic() -> None:
    definition = DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.03,
        negative_return_threshold=-0.03,
    )
    policy = DirectionalPolicy(
        policy_id="buy-all",
        direction=DirectionalPolicyDirection.BUY,
    )
    rows = (
        _observation("A", 0.05),
        _observation("B", -0.04),
        _observation("C", 0.01),
    )

    metrics = calculate_directional_metrics(
        observations=rows,
        policy=policy,
        definition=definition,
    )

    assert metrics.precision == 1 / 3
    assert metrics.recall == 1.0
    assert metrics.accepted_signals == 3
    assert metrics.expectancy == (0.05 - 0.04 + 0.01) / 3
    assert metrics.average_mae is not None
    assert metrics.average_mfe is not None


def test_confidence_interval_and_effective_sample_size() -> None:
    low, high = wilson_interval(7, 10)

    assert low is not None
    assert high is not None
    assert low < 0.70 < high
    clustered = tuple(_observation(f"SYM{i}", 0.04) for i in range(10))
    assert effective_sample_size(clustered) <= 10


def test_minimum_signal_and_concentration_constraints_are_enforced() -> None:
    report = build_precision_coverage_report(
        observations=tuple(_observation(f"A{i}", 0.05) for i in range(8)),
        direction=DirectionalPolicyDirection.BUY,
        constraints=PrecisionCoverageConstraints(
            minimum_completed_signals=100,
            minimum_year_signals=5,
            maximum_year_concentration=0.25,
            minimum_effective_sample_size=60,
        ),
    )

    reasons = {
        reason for point in report.frontier for reason in point.constraints.reason_codes
    }

    assert "INSUFFICIENT_COMPLETED_SIGNALS" in reasons
    assert "YEAR_CONCENTRATION_TOO_HIGH" in reasons
    assert report.production_influence is False


def test_frontier_and_pareto_are_deterministically_ordered() -> None:
    report = build_precision_coverage_report(
        direction=DirectionalPolicyDirection.BUY,
        constraints=PrecisionCoverageConstraints(
            minimum_completed_signals=5,
            minimum_year_signals=1,
            maximum_year_concentration=1.0,
            minimum_effective_sample_size=1,
            minimum_precision=0.0,
        ),
    )

    second_report = build_precision_coverage_report(
        direction=DirectionalPolicyDirection.BUY,
        constraints=PrecisionCoverageConstraints(
            minimum_completed_signals=5,
            minimum_year_signals=1,
            maximum_year_concentration=1.0,
            minimum_effective_sample_size=1,
            minimum_precision=0.0,
        ),
    )

    assert report.frontier
    assert pareto_frontier(report.frontier) == report.pareto_frontier
    assert [point.policy.policy_id for point in report.pareto_frontier] == [
        point.policy.policy_id for point in second_report.pareto_frontier
    ]


def test_nested_walk_forward_uses_untouched_outer_test_with_purge_and_embargo() -> None:
    rows = deterministic_research_observations()
    policies = (
        DirectionalPolicy(
            policy_id="buy-all",
            direction=DirectionalPolicyDirection.BUY,
        ),
    )

    folds = nested_walk_forward(
        observations=rows,
        policies=policies,
        definition=DirectionalOutcomeDefinition(
            family=DirectionalOutcomeFamily.BARRIER_FIRST,
            horizon_days=20,
        ),
        constraints=PrecisionCoverageConstraints(),
        purge_days=20,
        embargo_days=5,
    )

    assert folds
    assert all(fold.train_end < fold.test_start for fold in folds)
    assert all(fold.embargo_days == 5 for fold in folds)
    assert all(fold.selected_policy_id == "buy-all" for fold in folds)


def test_feature_lineage_and_retracement_ablation_are_reported() -> None:
    rows = deterministic_research_observations()
    definition = DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.BARRIER_FIRST,
        horizon_days=20,
    )

    lineage = feature_lineage_audit(rows)
    ablation = retracement_ablation(observations=rows, definition=definition)

    assert any(row.leakage_warning for row in lineage)
    assert {row.variant for row in ablation} == {
        "raw",
        "inverted",
        "conditioned_on_trend",
        "removed",
    }


def test_setup_analysis_classifies_buy_and_sell_structures() -> None:
    analysis = setup_directional_analysis(
        observations=deterministic_research_observations(),
        definition=DirectionalOutcomeDefinition(
            family=DirectionalOutcomeFamily.BARRIER_FIRST,
            horizon_days=20,
        ),
    )

    roles = {row.role.value for row in analysis}

    assert analysis
    assert roles <= {
        "BUY_ONLY",
        "SELL_ONLY",
        "BIDIRECTIONAL",
        "NON_PREDICTIVE",
        "INSUFFICIENT_SAMPLE",
    }


def test_calibration_report_and_policy_candidates_are_research_only() -> None:
    calibration = build_directional_calibration_report()
    candidates = build_policy_candidate_report()

    assert calibration.buckets
    assert calibration.production_influence is False
    assert candidates.candidates
    assert candidates.no_success_claim is True
    assert candidates.production_influence is False


def test_json_and_csv_exports(tmp_path) -> None:
    report = build_precision_coverage_report(direction=DirectionalPolicyDirection.SELL)
    json_path = tmp_path / "frontier.json"
    csv_path = tmp_path / "frontier.csv"
    calibration_path = tmp_path / "calibration.csv"

    export_precision_coverage_json(report, json_path)
    export_frontier_csv(report.frontier, csv_path)
    export_calibration_csv(build_directional_calibration_report(), calibration_path)

    payload = json.loads(json_path.read_text())
    csv_text = csv_path.read_text()

    assert payload["production_influence"] is False
    assert "policy_id,direction,precision" in csv_text
    assert "bucket,count,average_probability" in calibration_path.read_text()


def test_cli_precision_frontier_renders_required_fields() -> None:
    result = CliRunner().invoke(
        app,
        ["replay", "precision-coverage-frontier", "--direction", "buy"],
    )

    assert result.exit_code == 0
    assert "Bidirectional Precision-Coverage Frontier" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    assert "precision" in result.output
    assert "effective n" in result.output


def test_cli_policy_audit_calibration_and_candidates() -> None:
    runner = CliRunner()

    audit = runner.invoke(
        app,
        [
            "replay",
            "bidirectional-policy-audit",
            "--min-precision",
            "0.70",
            "--min-signals",
            "100",
        ],
    )
    calibration = runner.invoke(app, ["replay", "directional-calibration"])
    candidates = runner.invoke(
        app,
        ["replay", "directional-policy-candidates", "--group-by", "policy"],
    )

    assert audit.exit_code == 0
    assert "Bidirectional Policy Audit" in audit.output
    assert "Minimum Precision Target: 70.00%" in audit.output
    assert calibration.exit_code == 0
    assert "Directional Calibration" in calibration.output
    assert candidates.exit_code == 0
    assert "Directional Policy Candidates Grouped By policy" in candidates.output


def _observation(
    symbol: str,
    forward_return: float | None,
    *,
    upside_day: int | None = None,
    downside_day: int | None = None,
) -> DirectionalObservation:
    return DirectionalObservation(
        symbol=symbol,
        observed_at=date(2024, 1, 2),
        horizon_days=20,
        forward_return=forward_return,
        max_favorable_excursion=None
        if forward_return is None
        else max(forward_return, 0) + 0.01,
        max_adverse_excursion=None
        if forward_return is None
        else min(forward_return, 0) - 0.01,
        recommendation_score=0.60,
        posterior_probability=0.60,
        price_component=0.60,
        setup_quality=0.60,
        retracement_score=0.40,
        entry_timing="PREFERRED",
        regime="BULLISH",
        setup_type="breakout",
        trade_plan_quality=0.60,
        stop_distance_pct=0.05,
        expected_value=forward_return,
        confidence=0.60,
        completed=forward_return is not None,
        upside_barrier_day=upside_day,
        downside_barrier_day=downside_day,
    )
