from __future__ import annotations

import json
from datetime import date, timedelta

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import (
    BuyFeatureGroup,
    BuyModelConclusion,
    BuyModelKind,
    BuyModelSpec,
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    DirectionTimingCategory,
    PrecisionCoverageConstraints,
    build_buy_feature_lineage,
    build_buy_signal_reconstruction_report,
    evaluate_buy_model,
    export_buy_model_results_csv,
    export_buy_reconstruction_json,
    filter_buy_model_results,
    group_buy_report,
    run_backward_ablation,
    run_direction_timing_analysis,
    run_false_negative_recovery,
    run_false_positive_taxonomy,
    run_forward_feature_addition,
    run_regime_interaction_tests,
    run_retracement_buy_tests,
    run_setup_specialized_buy_models,
)


def test_baseline_models_are_reported() -> None:
    report = build_buy_signal_reconstruction_report(_observations())
    model_ids = {row.spec.model_id for row in report.baselines}

    assert "always-buy" in model_ids
    assert "current-production-score" in model_ids
    assert "price-only" in model_ids
    assert "full-current-stack" in model_ids
    assert report.production_influence is False


def test_feature_lineage_records_missingness_and_safety() -> None:
    lineage = build_buy_feature_lineage(_observations())
    by_group = {row.group: row for row in lineage}

    assert by_group[BuyFeatureGroup.PRICE_STRUCTURE].missingness == 0
    assert (
        by_group[BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS].look_ahead_safe is False
    )
    assert (
        BuyFeatureGroup.PRICE_STRUCTURE
        in by_group[BuyFeatureGroup.RETRACEMENT].overlaps_with
    )


def test_forward_feature_addition_is_deterministic() -> None:
    steps = run_forward_feature_addition(
        _observations(),
        definition=_definition(),
        constraints=_constraints(),
    )

    assert [step.candidate_group for step in steps[:3]] == [
        BuyFeatureGroup.PRICE_STRUCTURE,
        BuyFeatureGroup.VOLUME,
        BuyFeatureGroup.SUPPORT_RESISTANCE,
    ]
    assert steps[0].retained is True


def test_backward_ablation_and_retracement_variants() -> None:
    rows = _observations()
    ablation = run_backward_ablation(
        rows,
        definition=_definition(),
        constraints=_constraints(),
    )
    retracement = run_retracement_buy_tests(
        rows,
        definition=_definition(),
        constraints=_constraints(),
    )

    assert any(BuyFeatureGroup.RETRACEMENT in row.removed_groups for row in ablation)
    assert len(retracement) >= 4
    assert any(
        row.result.spec.model_id == "retracement-inverted" for row in retracement
    )


def test_two_stage_direction_timing_analysis() -> None:
    rows = run_direction_timing_analysis(_observations(), definition=_definition())
    categories = {row.category for row in rows}

    assert DirectionTimingCategory.DIRECTION_RIGHT_TIMING_RIGHT in categories
    assert DirectionTimingCategory.DIRECTION_RIGHT_TIMING_WRONG in categories


def test_setup_specialized_and_regime_interaction_outputs() -> None:
    rows = _observations()
    setups = run_setup_specialized_buy_models(
        rows,
        definition=_definition(),
        constraints=_constraints(),
    )
    regimes = run_regime_interaction_tests(
        rows,
        definition=_definition(),
        constraints=_constraints(),
    )

    assert {row.setup_type for row in setups}
    assert {row.regime for row in regimes}
    assert all(row.result.production_influence is False for row in setups)


def test_false_positive_taxonomy_and_false_negative_recovery() -> None:
    rows = _observations()
    model = evaluate_buy_model(
        rows,
        spec=BuyModelSpec(
            model_id="price-volume-test",
            name="Price volume test",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(BuyFeatureGroup.PRICE_STRUCTURE, BuyFeatureGroup.VOLUME),
            threshold=0.55,
        ),
        definition=_definition(),
        constraints=_constraints(),
    )

    false_positives = run_false_positive_taxonomy(
        rows,
        model=model,
        definition=_definition(),
    )
    false_negatives = run_false_negative_recovery(
        rows,
        model=model,
        definition=_definition(),
    )

    assert false_positives
    assert false_negatives
    assert false_positives[0].preventability.value


def test_minimal_model_report_and_grouping() -> None:
    report = build_buy_signal_reconstruction_report(_observations())

    assert report.best_minimal_model is not None
    assert report.final_conclusion in set(BuyModelConclusion)
    assert "PRODUCTION" not in "\n".join(group_buy_report(report, "feature"))
    assert filter_buy_model_results(report, "price")


def test_json_and_csv_exports(tmp_path) -> None:
    report = build_buy_signal_reconstruction_report(_observations())
    json_path = tmp_path / "buy.json"
    csv_path = tmp_path / "buy.csv"

    export_buy_reconstruction_json(report, json_path)
    export_buy_model_results_csv(report.comparison_table, csv_path)

    payload = json.loads(json_path.read_text())
    assert payload["production_influence"] is False
    assert "model_id,name,precision" in csv_path.read_text()


def test_cli_buy_reconstruction_and_subreports() -> None:
    runner = CliRunner()
    reconstruction = runner.invoke(app, ["replay", "buy-signal-reconstruction"])
    ablation = runner.invoke(app, ["replay", "buy-feature-ablation"])
    positives = runner.invoke(app, ["replay", "buy-false-positive-audit"])
    negatives = runner.invoke(app, ["replay", "buy-false-negative-audit"])
    models = runner.invoke(app, ["replay", "buy-minimal-models", "--group-by", "setup"])
    frontier = runner.invoke(
        app,
        ["replay", "buy-precision-frontier", "--model", "price"],
    )

    assert reconstruction.exit_code == 0
    assert "BUY Directional Signal Reconstruction" in reconstruction.output
    assert "PRODUCTION_INFLUENCE=false" in reconstruction.output
    assert ablation.exit_code == 0
    assert "BUY Feature Ablation" in ablation.output
    assert positives.exit_code == 0
    assert "BUY False Positive Audit" in positives.output
    assert negatives.exit_code == 0
    assert "BUY False Negative Audit" in negatives.output
    assert models.exit_code == 0
    assert "Grouped By setup" in models.output
    assert frontier.exit_code == 0
    assert "BUY Minimal Models" in frontier.output


def _definition() -> DirectionalOutcomeDefinition:
    return DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )


def _constraints() -> PrecisionCoverageConstraints:
    return PrecisionCoverageConstraints(
        minimum_completed_signals=3,
        minimum_fold_signals=1,
        minimum_year_signals=1,
        maximum_year_concentration=1.0,
        maximum_setup_concentration=1.0,
        maximum_regime_concentration=1.0,
        minimum_effective_sample_size=1,
        minimum_precision=0.0,
    )


def _observations() -> tuple[DirectionalObservation, ...]:
    rows: list[DirectionalObservation] = []
    start = date(2020, 1, 3)
    returns = (0.08, -0.05, 0.04, -0.03, 0.06, -0.04) * 4
    for index, forward_return in enumerate(returns):
        rows.append(
            DirectionalObservation(
                symbol=f"SYM{index % 4}",
                observed_at=start + timedelta(days=90 * index),
                horizon_days=20,
                forward_return=forward_return,
                max_favorable_excursion=max(forward_return, 0) + 0.02,
                max_adverse_excursion=min(forward_return, 0) - 0.02,
                recommendation_score=0.70 if index % 2 == 0 else 0.45,
                posterior_probability=0.65 if index % 2 == 0 else 0.35,
                price_component=0.75 if index % 2 == 0 else 0.40,
                setup_quality=0.70 if index % 3 != 1 else 0.35,
                retracement_score=0.30 if index % 2 == 0 else 0.75,
                entry_timing="PREFERRED_ENTRY" if index % 3 == 0 else "LATE_ENTRY",
                regime="BULLISH" if index % 4 != 1 else "BEARISH",
                setup_type="MOMENTUM BREAKOUT" if index % 2 == 0 else "FAILED BREAKOUT",
                trade_plan_quality=0.65 if index % 2 == 0 else 0.30,
                stop_distance_pct=0.05 if index % 2 == 0 else 0.13,
                expected_value=forward_return,
                confidence=0.70 if index % 2 == 0 else 0.40,
                completed=True,
                sector="TEST",
                feature_values=(
                    ("price", 0.75 if index % 2 == 0 else 0.40),
                    ("volume", 0.70 if index % 3 == 0 else 0.30),
                    ("support", 0.65 if index % 2 == 0 else 0.35),
                    ("trend", 0.70 if index % 2 == 0 else 0.35),
                    ("relative_strength", 0.70 if index % 2 == 0 else 0.30),
                    ("retracement", 0.30 if index % 2 == 0 else 0.75),
                    ("trade_plan", 0.65 if index % 2 == 0 else 0.30),
                ),
            )
        )
    return tuple(rows)
