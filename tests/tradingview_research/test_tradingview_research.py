"""Deterministic tests for the TradingView Research Laboratory."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.tradingview_research.aggregation import ResearchAggregationEngine
from alpha.tradingview_research.baseline import (
    baseline_manifest,
    canonical_baseline_configuration,
    experiment_template,
)
from alpha.tradingview_research.batch import BatchRunPlanner
from alpha.tradingview_research.comparison import ComparativeResearchEngine
from alpha.tradingview_research.grid import WeightGridGenerator
from alpha.tradingview_research.models import (
    PRODUCTION_INFLUENCE,
    ComparisonOutcome,
    ExperimentObservation,
    IndicatorId,
    ObservationRole,
    PerformanceMetrics,
    PromotionDecision,
    PromotionReason,
    ResearchPartition,
    TradingViewExperiment,
    UniverseMember,
    WeightRange,
)
from alpha.tradingview_research.promotion import CandidatePromotionEngine
from alpha.tradingview_research.ranking import CandidateRankingEngine
from alpha.tradingview_research.registry import (
    TradingViewResearchRegistry,
    experiment_from_dict,
)
from alpha.tradingview_research.rendering import render_experiment_report
from alpha.tradingview_research.variants import LabVariantGenerator

RUNNER = CliRunner()


def _metrics(
    *,
    expectancy: str,
    drawdown: str,
    trades: int = 20,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        trade_count=trades,
        win_rate_pct=Decimal("55"),
        profit_factor=Decimal("1.40"),
        expectancy=Decimal(expectancy),
        maximum_drawdown_pct=Decimal(drawdown),
        net_return_pct=Decimal("8.5"),
        average_winner=Decimal("2.2"),
        average_loser=Decimal("1.1"),
        stop_out_rate_pct=Decimal("30"),
        average_holding_period=Decimal("8"),
    )


def _observation(
    role: ObservationRole,
    partition: ResearchPartition,
    symbol: str,
    sector: str,
    start: date,
    end: date,
    *,
    expectancy: str,
    drawdown: str,
) -> ExperimentObservation:
    return ExperimentObservation(
        role=role,
        partition=partition,
        symbol=symbol,
        sector=sector,
        period_start=start,
        period_end=end,
        metrics=_metrics(expectancy=expectancy, drawdown=drawdown),
    )


def _experiment(
    experiment_id: str = "trl-evidence-001",
    *,
    include_holdout: bool = True,
    holdout_overlaps: bool = False,
) -> TradingViewExperiment:
    baseline = canonical_baseline_configuration()
    treatment = replace(baseline, name="TRL_TEST_TREATMENT")
    periods = (
        (ResearchPartition.DEVELOPMENT, date(2015, 1, 1), date(2018, 12, 31)),
        (ResearchPartition.VALIDATION, date(2019, 1, 1), date(2021, 12, 31)),
        (
            ResearchPartition.HOLDOUT,
            date(2021, 1, 1) if holdout_overlaps else date(2022, 1, 1),
            date(2024, 12, 31),
        ),
    )
    observations: list[ExperimentObservation] = []
    for partition, start, end in periods:
        if partition is ResearchPartition.HOLDOUT and not include_holdout:
            continue
        for symbol, sector in (("AAA", "BANKING"), ("BBB", "IT")):
            observations.extend(
                (
                    _observation(
                        ObservationRole.ALPHA_BASELINE,
                        partition,
                        symbol,
                        sector,
                        start,
                        end,
                        expectancy="0.40",
                        drawdown="12.0",
                    ),
                    _observation(
                        ObservationRole.TREATMENT,
                        partition,
                        symbol,
                        sector,
                        start,
                        end,
                        expectancy="0.55",
                        drawdown="11.0",
                    ),
                )
            )
    return TradingViewExperiment(
        experiment_id=experiment_id,
        title="Measured TRL evidence",
        purpose="Test a candidate against exact Alpha cohorts.",
        experiment_date=date(2025, 1, 15),
        baseline=baseline,
        treatment=treatment,
        observations=tuple(observations),
    )


def test_canonical_baseline_is_stable_and_research_only() -> None:
    first = canonical_baseline_configuration()
    second = canonical_baseline_configuration()
    enabled = {item.indicator: item.enabled for item in first.indicators}

    assert first.configuration_id == second.configuration_id
    assert sum(item.weight for item in first.weights) == Decimal("100.00")
    assert enabled[IndicatorId.PRICE_STRUCTURE]
    assert not enabled[IndicatorId.RSI]
    assert not PRODUCTION_INFLUENCE
    assert baseline_manifest()["production_influence"] is False
    assert experiment_template()["experiment_date"] == "YYYY-MM-DD"


def test_comparison_requires_exact_population_match() -> None:
    experiment = _experiment()
    unmatched = replace(
        experiment.observations[-1],
        period_end=date(2025, 1, 1),
    )
    changed = replace(
        experiment,
        observations=experiment.observations[:-1] + (unmatched,),
    )

    report = ComparativeResearchEngine().compare(changed)

    assert len(report.cohorts) == 5
    assert report.unmatched_baseline_cohorts == 1
    assert report.unmatched_treatment_cohorts == 1
    assert all(row.outcome is ComparisonOutcome.IMPROVED for row in report.cohorts)


def test_promotion_requires_all_partitions_symbols_and_sectors() -> None:
    experiment = _experiment(include_holdout=False)
    comparison = ComparativeResearchEngine().compare(experiment)
    assessment = CandidatePromotionEngine().assess(experiment, comparison)

    assert assessment.decision is PromotionDecision.REJECT
    assert PromotionReason.MISSING_HOLDOUT in assessment.failed_reasons
    assert not assessment.production_influence


def test_complete_measured_evidence_promotes_only_to_alpha_replay() -> None:
    experiment = _experiment()
    comparison = ComparativeResearchEngine().compare(experiment)
    assessment = CandidatePromotionEngine().assess(experiment, comparison)

    assert comparison.improved_cohorts == 6
    assert comparison.weighted_expectancy_improvement == Decimal("0.15")
    assert comparison.weighted_drawdown_improvement == Decimal("1.0")
    assert assessment.decision is PromotionDecision.PROMOTE_TO_ALPHA_REPLAY
    assert assessment.promote
    assert "not approval for production" in assessment.explanation


def test_partition_overlap_is_rejected_as_leakage() -> None:
    experiment = _experiment(holdout_overlaps=True)
    comparison = ComparativeResearchEngine().compare(experiment)
    assessment = CandidatePromotionEngine().assess(experiment, comparison)

    assert PromotionReason.PARTITION_LEAKAGE in assessment.failed_reasons


def test_missing_metrics_never_become_improvement() -> None:
    baseline = canonical_baseline_configuration()
    empty = PerformanceMetrics(
        trade_count=0,
        win_rate_pct=None,
        profit_factor=None,
        expectancy=None,
        maximum_drawdown_pct=None,
        net_return_pct=None,
        average_winner=None,
        average_loser=None,
    )
    observations = tuple(
        ExperimentObservation(
            role=role,
            partition=ResearchPartition.DEVELOPMENT,
            symbol="AAA",
            sector="IT",
            period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31),
            metrics=empty,
        )
        for role in ObservationRole
    )
    experiment = TradingViewExperiment(
        experiment_id="trl-empty",
        title="No observed trades",
        purpose="Prove unavailable metrics fail closed.",
        experiment_date=date(2025, 1, 1),
        baseline=baseline,
        treatment=replace(baseline, name="TRL_EMPTY"),
        observations=observations,
    )

    comparison = ComparativeResearchEngine().compare(experiment)
    assessment = CandidatePromotionEngine().assess(experiment, comparison)

    assert comparison.cohorts[0].outcome is ComparisonOutcome.INSUFFICIENT_EVIDENCE
    assert comparison.weighted_expectancy_improvement is None
    assert assessment.decision is PromotionDecision.REJECT


def test_weight_grid_is_bounded_and_development_only() -> None:
    baseline = canonical_baseline_configuration()
    ranges = (
        WeightRange("price_structure", Decimal("10"), Decimal("20"), Decimal("10")),
        WeightRange("volume", Decimal("10"), Decimal("20"), Decimal("10")),
    )

    variants = WeightGridGenerator().generate(
        baseline,
        ranges,
        partition=ResearchPartition.DEVELOPMENT,
    )

    assert len(variants) == 4
    assert len({item.configuration_id for item in variants}) == 4
    with pytest.raises(ValueError, match="only on DEVELOPMENT"):
        WeightGridGenerator().generate(
            baseline,
            ranges,
            partition=ResearchPartition.HOLDOUT,
        )
    with pytest.raises(ValueError, match="limit is 3"):
        WeightGridGenerator().generate(
            baseline,
            ranges,
            partition=ResearchPartition.DEVELOPMENT,
            maximum_variants=3,
        )


def test_complete_lab_variant_families_are_predeclared() -> None:
    baseline = canonical_baseline_configuration()
    generator = LabVariantGenerator()

    ablations = generator.component_ablation(baseline)
    risk_variants = generator.stop_exit(baseline)
    timeframe_variants = generator.multi_timeframe(baseline)

    assert len(ablations) == 8
    assert ablations[0].name == "TRL_ABLATION_BASELINE"
    assert len(risk_variants) == 54
    assert len(timeframe_variants) == 125
    assert len({item.configuration_id for item in risk_variants}) == 54
    assert len({item.configuration_id for item in timeframe_variants}) == 125
    assert baseline == canonical_baseline_configuration()


def test_batch_plan_is_stable_and_one_run_per_symbol_partition() -> None:
    baseline = canonical_baseline_configuration()
    members = (
        UniverseMember("BBB", "IT"),
        UniverseMember("AAA", "BANKING"),
    )
    partitions = (ResearchPartition.VALIDATION, ResearchPartition.DEVELOPMENT)

    first = BatchRunPlanner().plan(baseline, members, partitions)
    second = BatchRunPlanner().plan(baseline, members, partitions)

    assert first == second
    assert len(first) == 4
    assert len({item.run_id for item in first}) == 4


def test_sector_and_symbol_labs_aggregate_measured_evidence() -> None:
    experiment = _experiment()
    engine = ResearchAggregationEngine()

    sectors = engine.sector_summaries(experiment)
    distribution = engine.universe_distribution(
        experiment,
        role=ObservationRole.TREATMENT,
        partition=ResearchPartition.VALIDATION,
    )

    assert len(sectors) == 6
    assert all(item.recommendation is ComparisonOutcome.IMPROVED for item in sectors)
    assert all(item.expectancy == Decimal("0.55") for item in sectors)
    assert distribution.symbols == ("AAA", "BBB")
    assert distribution.expectancy.minimum == Decimal("0.55")
    assert distribution.expectancy.median == Decimal("0.55")
    assert distribution.expectancy.maximum == Decimal("0.55")
    assert distribution.expectancy.missing_count == 0


def test_aggregation_exposes_missing_metrics_instead_of_hiding_them() -> None:
    experiment = _experiment()
    treatment_index = next(
        index
        for index, item in enumerate(experiment.observations)
        if item.role is ObservationRole.TREATMENT
        and item.partition is ResearchPartition.VALIDATION
        and item.symbol == "AAA"
    )
    source = experiment.observations[treatment_index]
    missing_profit_factor = replace(source.metrics, profit_factor=None)
    observations = list(experiment.observations)
    observations[treatment_index] = replace(source, metrics=missing_profit_factor)
    changed = replace(experiment, observations=tuple(observations))
    engine = ResearchAggregationEngine()

    sector = next(
        item
        for item in engine.sector_summaries(changed)
        if item.partition is ResearchPartition.VALIDATION and item.sector == "BANKING"
    )
    distribution = engine.universe_distribution(
        changed,
        role=ObservationRole.TREATMENT,
        partition=ResearchPartition.VALIDATION,
    )

    assert sector.profit_factor is None
    assert distribution.profit_factor.available_count == 1
    assert distribution.profit_factor.missing_count == 1


def test_registry_is_idempotent_immutable_and_exportable(tmp_path: Path) -> None:
    registry = TradingViewResearchRegistry(tmp_path / "registry.json")
    experiment = _experiment()

    assert registry.record(experiment)
    assert not registry.record(experiment)
    with pytest.raises(ValueError, match="immutable TRL experiment conflict"):
        registry.record(replace(experiment, title="Mutated evidence"))

    restored = registry.load()
    assert restored == (experiment,)
    assert experiment_from_dict(experiment.as_dict()) == experiment
    assert '"production_influence": false' in registry.json_text()
    assert "experiment_id,title" in registry.csv_text()


def test_ranking_uses_measured_deltas_without_synthetic_score() -> None:
    promoted = _experiment("trl-promoted")
    rejected = _experiment("trl-rejected", include_holdout=False)

    ranking = CandidateRankingEngine().rank((rejected, promoted))

    assert ranking[0].experiment_id == "trl-promoted"
    assert ranking[0].promotion_decision is PromotionDecision.PROMOTE_TO_ALPHA_REPLAY
    assert ranking[1].primary_rejection is not None


def test_report_renders_evidence_and_production_isolation() -> None:
    experiment = _experiment()
    comparison = ComparativeResearchEngine().compare(experiment)
    promotion = CandidatePromotionEngine().assess(experiment, comparison)

    text = render_experiment_report(experiment, comparison, promotion)

    assert "Matched Cohorts: 6" in text
    assert "PROMOTE_TO_ALPHA_REPLAY" in text
    assert "PRODUCTION_INFLUENCE=false" in text


def test_trl_cli_baseline_template_registry_report_and_promotion(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.json"
    input_path = tmp_path / "experiment.json"
    input_path.write_text(
        json.dumps(_experiment().as_dict()),
        encoding="utf-8",
    )

    baseline_result = RUNNER.invoke(app, ["trl", "baseline"])
    template_result = RUNNER.invoke(
        app,
        ["trl", "template", "--output", str(tmp_path / "template.json")],
    )
    register_result = RUNNER.invoke(
        app,
        [
            "trl",
            "register",
            "--input",
            str(input_path),
            "--registry",
            str(registry),
        ],
    )
    report_result = RUNNER.invoke(
        app,
        [
            "trl",
            "report",
            "--experiment-id",
            "trl-evidence-001",
            "--registry",
            str(registry),
        ],
    )
    promotion_result = RUNNER.invoke(
        app,
        [
            "trl",
            "promote",
            "--experiment-id",
            "trl-evidence-001",
            "--registry",
            str(registry),
        ],
    )

    assert baseline_result.exit_code == 0
    assert '"ALPHA_CANONICAL_BASELINE"' in baseline_result.stdout
    assert template_result.exit_code == 0
    assert "OBSERVED_METRICS_REQUIRED=true" in template_result.stdout
    assert register_result.exit_code == 0
    assert "Status: RECORDED" in register_result.stdout
    assert report_result.exit_code == 0
    assert "TradingView Research Laboratory Report" in report_result.stdout
    assert promotion_result.exit_code == 0
    assert "Promote: YES" in promotion_result.stdout
    assert "PRODUCTION_INFLUENCE=false" in promotion_result.stdout


def test_trl_cli_grid_batch_rank_registry_and_scripts(tmp_path: Path) -> None:
    grid_input = tmp_path / "grid.json"
    grid_output = tmp_path / "variants.json"
    grid_input.write_text(
        json.dumps(
            {
                "partition": "DEVELOPMENT",
                "ranges": [
                    {
                        "component": "price_structure",
                        "minimum": "15",
                        "maximum": "25",
                        "step": "5",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    batch_input = tmp_path / "batch.json"
    batch_output = tmp_path / "runs.json"
    batch_input.write_text(
        json.dumps(
            {
                "members": [
                    {"symbol": "AAA", "sector": "BANKING"},
                    {"symbol": "BBB", "sector": "IT"},
                ],
                "partitions": ["DEVELOPMENT", "VALIDATION"],
            }
        ),
        encoding="utf-8",
    )
    registry_path = tmp_path / "empty_registry.json"

    grid_result = RUNNER.invoke(
        app,
        [
            "trl",
            "weight-grid",
            "--input",
            str(grid_input),
            "--output",
            str(grid_output),
        ],
    )
    batch_result = RUNNER.invoke(
        app,
        [
            "trl",
            "batch-plan",
            "--input",
            str(batch_input),
            "--output",
            str(batch_output),
        ],
    )
    rank_result = RUNNER.invoke(
        app,
        ["trl", "rank", "--registry", str(registry_path)],
    )
    registry_result = RUNNER.invoke(
        app,
        ["trl", "registry", "--registry", str(registry_path)],
    )
    scripts_result = RUNNER.invoke(app, ["trl", "scripts"])
    variant_output = tmp_path / "ablation_variants.json"
    variant_result = RUNNER.invoke(
        app,
        [
            "trl",
            "variant-plan",
            "--family",
            "COMPONENT_ABLATION",
            "--output",
            str(variant_output),
        ],
    )

    assert grid_result.exit_code == 0
    assert "Variants: 3" in grid_result.stdout
    assert "HOLDOUT_OPTIMIZATION=false" in grid_result.stdout
    assert batch_result.exit_code == 0
    assert "Runs: 4" in batch_result.stdout
    assert rank_result.exit_code == 0
    assert "No measured TradingView experiments" in rank_result.stdout
    assert registry_result.exit_code == 0
    assert "Experiments: 0" in registry_result.stdout
    assert scripts_result.exit_code == 0
    assert "Scripts: 4" in scripts_result.stdout
    assert "PINE_STATIC_VALIDATION=PASS" in scripts_result.stdout
    assert variant_result.exit_code == 0
    assert "Variants: 8" in variant_result.stdout
    assert "RESULT_AWARE_SELECTION=false" in variant_result.stdout


def test_trl_cli_sector_and_symbol_reports(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    TradingViewResearchRegistry(registry_path).record(_experiment())

    sector_result = RUNNER.invoke(
        app,
        [
            "trl",
            "sector-report",
            "--experiment-id",
            "trl-evidence-001",
            "--registry",
            str(registry_path),
        ],
    )
    symbol_result = RUNNER.invoke(
        app,
        [
            "trl",
            "symbol-report",
            "--experiment-id",
            "trl-evidence-001",
            "--partition",
            "VALIDATION",
            "--registry",
            str(registry_path),
        ],
    )

    assert sector_result.exit_code == 0
    assert "TRL Sector Laboratory" in sector_result.stdout
    assert "BANKING" in sector_result.stdout
    assert "recommendation=IMPROVED" in sector_result.stdout
    assert symbol_result.exit_code == 0
    assert "TRL Symbol Laboratory" in symbol_result.stdout
    assert "median=0.55" in symbol_result.stdout
    assert "missing=0" in symbol_result.stdout


def test_trl_documentation_and_dashboard_artifacts_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    architecture = (
        root / "docs" / "pine" / "TRADINGVIEW_RESEARCH_LABORATORY_V2.md"
    ).read_text(encoding="utf-8")
    protocol = (root / "docs" / "pine" / "TRL_RESEARCH_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    labs = tuple(sorted((root / "tradingview" / "labs").glob("*.pine")))

    assert len(labs) == 4
    assert "PROMOTE_TO_ALPHA_REPLAY" in architecture
    assert "PRODUCTION_INFLUENCE=false" in architecture
    assert "Never tune" in protocol
    assets = root / "docs" / "pine" / "assets"
    assert (assets / "trl_dashboard_reference.png").is_file()
    assert (assets / "trl_comparison_reference.png").is_file()
