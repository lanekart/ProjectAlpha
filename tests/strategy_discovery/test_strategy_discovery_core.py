from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.candidate_strategy_generator import (
    CandidateStrategyGenerator,
)
from alpha.strategy_discovery.discovery_service import (
    StrategyDiscoveryService,
    classify_strategy,
)
from alpha.strategy_discovery.feature_manifest import FeatureManifest
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_discovery.models import (
    ConditionOperator,
    DiscoveryDataset,
    DiscoveryRow,
    DiscoveryRunConfig,
    GeneralisationClassification,
    HistoricalTruthClass,
    MultipleTestingResult,
    RobustnessResult,
    StrategyCondition,
    StrategyFamily,
    StrategySpecification,
)
from alpha.strategy_discovery.multiple_testing_control import MultipleTestingControl
from alpha.strategy_discovery.parameter_stability import ParameterStabilityEngine
from alpha.strategy_discovery.rendering import render_discovery_report
from alpha.strategy_discovery.robustness_engine import RobustnessEngine
from alpha.strategy_discovery.shadow_candidate_publisher import (
    ShadowCandidatePublisher,
)
from alpha.strategy_discovery.strategy_evaluator import StrategyEvaluator
from alpha.strategy_discovery.strategy_registry import StrategyRegistry
from alpha.strategy_discovery.walk_forward_engine import WalkForwardEngine


def test_feature_manifest_quarantines_future_and_invalid_features() -> None:
    manifest = FeatureManifest()

    assert "price_component" in manifest.usable_feature_names
    assert "realised_return_pct" not in manifest.usable_feature_names
    outcome = next(
        item for item in manifest.definitions if item.name == "realised_return_pct"
    )
    assert outcome.available_at_decision_time is False
    with pytest.raises(ValueError, match="quarantined"):
        manifest.require_usable("market_regime")


def test_discovery_row_rejects_future_feature_timestamp() -> None:
    created = datetime(2025, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="feature timestamp"):
        _row(0, feature_timestamp=created + timedelta(days=1))


def test_candidate_generation_is_bounded_deterministic_and_hashed() -> None:
    dataset = _dataset(90)
    generator = CandidateStrategyGenerator()
    config = DiscoveryRunConfig(maximum_conditions_per_strategy=2)

    first, first_manifest = generator.generate(dataset=dataset, config=config)
    second, second_manifest = generator.generate(dataset=dataset, config=config)

    assert first == second
    assert first_manifest == second_manifest
    assert first_manifest.total_variants == len(first)
    assert all(len(item.conditions) <= 2 or item.benchmark for item in first)
    assert len({item.strategy_hash for item in first}) == len(first)
    assert first[0].strategy_version == "STRATEGY_RESEARCH_V001"


def test_chronological_split_enforces_purge_and_untouched_holdout() -> None:
    partition = WalkForwardEngine().partition(
        dataset=_dataset(100),
        config=DiscoveryRunConfig(purge_gap_days=3),
    )

    assert partition.training_rows
    assert partition.validation_rows
    assert partition.holdout_rows
    assert max(row.candidate_timestamp for row in partition.training_rows) < min(
        row.candidate_timestamp for row in partition.validation_rows
    ) - timedelta(days=3)
    assert not (
        {row.candidate_id for row in partition.validation_rows}
        & {row.candidate_id for row in partition.holdout_rows}
    )


def test_evaluator_deducts_explicit_costs_and_calculates_expectancy() -> None:
    rows = tuple(_row(index, realised_return=Decimal("2")) for index in range(5))
    strategy = _strategy()
    metrics = StrategyEvaluator().metrics(
        strategy=strategy,
        rows=rows,
        config=DiscoveryRunConfig(),
    )

    assert metrics.completed_trades == 5
    assert metrics.gross_expectancy_pct == Decimal("2.00")
    assert metrics.round_trip_cost_pct == Decimal("0.3")
    assert metrics.expectancy_pct == Decimal("1.70")
    assert metrics.maximum_drawdown_pct == Decimal("0.00")


def test_evaluator_reports_profit_factor_and_precision_interval() -> None:
    rows = tuple(
        _row(index, realised_return=Decimal("2") if index < 3 else Decimal("-1"))
        for index in range(5)
    )
    metrics = StrategyEvaluator().metrics(
        strategy=_strategy(),
        rows=rows,
        config=DiscoveryRunConfig(),
    )

    assert metrics.precision_pct == Decimal("60.00")
    assert metrics.precision_ci_low_pct is not None
    assert metrics.precision_ci_high_pct is not None
    assert metrics.profit_factor == Decimal("1.96")
    assert metrics.maximum_drawdown_pct == Decimal("2.58")


def test_parameter_perturbation_and_multiple_testing_are_deterministic() -> None:
    strategy = _strategy(threshold="70")
    stability = ParameterStabilityEngine().evaluate(
        strategy=strategy,
        rows=tuple(_row(index) for index in range(5)),
        config=DiscoveryRunConfig(),
    )
    first = MultipleTestingControl().evaluate(
        strategy_version=strategy.strategy_version,
        returns=(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
        hypotheses_tested=20,
    )
    second = MultipleTestingControl().evaluate(
        strategy_version=strategy.strategy_version,
        returns=(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
        hypotheses_tested=20,
    )

    assert stability.variants_tested == 2
    assert len(stability.expectancies_pct) == 2
    assert first == second
    assert first.hypotheses_tested == 20


def test_reconstructed_population_can_never_qualify_for_shadow() -> None:
    dataset = _dataset(100)
    partition = WalkForwardEngine().partition(
        dataset=dataset,
        config=DiscoveryRunConfig(),
    )
    evaluation = StrategyEvaluator().walk_forward_evaluation(
        strategy=_strategy(),
        partition=partition,
        rows_by_id={row.candidate_id: row for row in dataset.rows},
        config=DiscoveryRunConfig(),
    )
    classification, reasons = classify_strategy(
        dataset=dataset,
        evaluation=evaluation,
        robustness=RobustnessResult(
            strategy_version=evaluation.strategy.strategy_version,
            parameter_perturbation_passed=True,
            feature_ablation_passed=True,
            cost_stress_passed=True,
            delayed_entry_status="UNAVAILABLE",
            missed_fill_passed=True,
            stop_gap_status="UNAVAILABLE",
            bootstrap_expectancy_low_pct=Decimal("1"),
            bootstrap_expectancy_high_pct=Decimal("2"),
            fold_consistency_pct=Decimal("100"),
            symbol_concentration_pct=Decimal("10"),
            setup_concentration_pct=Decimal("10"),
            winner_concentration_pct=Decimal("10"),
            weaknesses=(),
        ),
        multiple_testing=MultipleTestingResult(
            strategy_version=evaluation.strategy.strategy_version,
            raw_p_value=Decimal("0.001"),
            adjusted_p_value=Decimal("0.01"),
            hypotheses_tested=10,
            adjustment_method="BONFERRONI",
            statistically_significant=True,
        ),
        config=DiscoveryRunConfig(),
    )

    assert classification is GeneralisationClassification.INVALID_DATA
    assert any("reconstructed" in reason for reason in reasons)


def test_minimum_sample_and_overfit_classifications_are_explicit() -> None:
    config = DiscoveryRunConfig()
    small = _authoritative_dataset(20)
    small_partition = WalkForwardEngine().partition(dataset=small, config=config)
    small_evaluation = StrategyEvaluator().walk_forward_evaluation(
        strategy=_strategy(),
        partition=small_partition,
        rows_by_id={row.candidate_id: row for row in small.rows},
        config=config,
    )
    classification, _ = classify_strategy(
        dataset=small,
        evaluation=small_evaluation,
        robustness=_passing_robustness(),
        multiple_testing=_significant_test(),
        config=config,
    )
    assert classification is GeneralisationClassification.INSUFFICIENT_SAMPLE

    full = _authoritative_dataset(100)
    full_partition = WalkForwardEngine().partition(dataset=full, config=config)
    evaluation = StrategyEvaluator().walk_forward_evaluation(
        strategy=_strategy(),
        partition=full_partition,
        rows_by_id={row.candidate_id: row for row in full.rows},
        config=config,
    )
    positive_folds = tuple(
        replace(
            item,
            metrics=replace(item.metrics, expectancy_pct=Decimal("1")),
        )
        for item in evaluation.fold_evaluations
    )
    overfit = replace(
        evaluation,
        training_metrics=replace(
            evaluation.training_metrics,
            expectancy_pct=Decimal("1"),
        ),
        validation_metrics=replace(
            evaluation.validation_metrics,
            expectancy_pct=Decimal("-1"),
        ),
        fold_evaluations=positive_folds,
    )
    classification, _ = classify_strategy(
        dataset=full,
        evaluation=overfit,
        robustness=_passing_robustness(),
        multiple_testing=_significant_test(),
        config=config,
    )
    assert classification is GeneralisationClassification.OVERFIT


def test_robustness_reports_ablation_and_concentration() -> None:
    dataset = _dataset(100)
    config = DiscoveryRunConfig()
    partition = WalkForwardEngine().partition(dataset=dataset, config=config)
    evaluation = StrategyEvaluator().walk_forward_evaluation(
        strategy=_strategy(),
        partition=partition,
        rows_by_id={row.candidate_id: row for row in dataset.rows},
        config=config,
    )
    result = RobustnessEngine().evaluate(
        strategy=evaluation.strategy,
        evaluation=evaluation,
        partition=partition,
        config=config,
    )

    assert isinstance(result.feature_ablation_passed, bool)
    assert result.symbol_concentration_pct is not None
    assert result.setup_concentration_pct is not None
    assert result.delayed_entry_status.startswith("UNAVAILABLE")
    assert result.stop_gap_status.startswith("UNAVAILABLE")


def test_holdout_access_is_single_use_and_auditable(tmp_path: Path) -> None:
    registry = StrategyRegistry(tmp_path / "strategy.json")
    first = registry.record_holdout_access(
        dataset_version="dataset-v1",
        strategy_versions=("STRATEGY_RESEARCH_V001",),
        purpose="ONE_TIME_FINAL_SHORTLIST_EVALUATION",
        result_hash="result-hash",
    )
    second = registry.record_holdout_access(
        dataset_version="dataset-v1",
        strategy_versions=("STRATEGY_RESEARCH_V001",),
        purpose="ONE_TIME_FINAL_SHORTLIST_EVALUATION",
        result_hash="result-hash",
    )

    assert first == second
    assert len(registry.holdout_accesses()) == 1
    with pytest.raises(ValueError, match="already accessed"):
        registry.record_holdout_access(
            dataset_version="dataset-v1",
            strategy_versions=("STRATEGY_RESEARCH_V002",),
            purpose="ONE_TIME_FINAL_SHORTLIST_EVALUATION",
            result_hash="different",
        )


def test_registry_exports_and_shadow_publication_fail_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report = service.report()
    json_path = service.registry.export_json(tmp_path / "registry-export.json")
    csv_path = service.registry.export_csv(tmp_path / "registry-export.csv")
    shadow_path = tmp_path / "shadow-cohorts.json"

    assert json_path.exists()
    assert csv_path.read_text(encoding="utf-8").startswith("dataset_version,rank")
    assert ShadowCandidatePublisher(shadow_path).publish(report) is None
    assert not shadow_path.exists()
    assert report.decision == "NO_GENERALISABLE_STRATEGY_FOUND"


def test_report_is_readable_and_registers_ird_research(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report = service.report()
    rendered = "\n".join(render_discovery_report(report))
    experiments = service.research_registry.load()

    assert "Walk-Forward Strategy Discovery Report" in rendered
    assert "Final Strategy Decision: NO_GENERALISABLE_STRATEGY_FOUND" in rendered
    assert "PRODUCTION_INFLUENCE=false" in rendered
    assert len(experiments) == 1
    assert experiments[0].subsystem.value == "STRATEGY_DISCOVERY"
    assert experiments[0].production_influence is False


def _dataset(count: int) -> DiscoveryDataset:
    rows = tuple(
        _row(index, realised_return=Decimal("2") if index % 3 else Decimal("-1"))
        for index in range(count)
    )
    return DiscoveryDataset(
        dataset_version="strategy-discovery-v1-reconstructed-test",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test-ledger",
        source_hash="source-hash",
        population_class=HistoricalTruthClass.RECONSTRUCTED,
        rows=rows,
        exclusions=(),
        quarantined_population=0,
    )


def _authoritative_dataset(count: int) -> DiscoveryDataset:
    reconstructed = _dataset(count)
    return replace(
        reconstructed,
        dataset_version="strategy-discovery-v1-authoritative-test",
        population_class=HistoricalTruthClass.AUTHORITATIVE,
        rows=tuple(
            replace(row, truth_class=HistoricalTruthClass.AUTHORITATIVE)
            for row in reconstructed.rows
        ),
    )


def _row(
    index: int,
    *,
    feature_timestamp: datetime | None = None,
    realised_return: Decimal = Decimal("1"),
) -> DiscoveryRow:
    created = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return DiscoveryRow(
        candidate_id=f"candidate-{index}",
        candidate_timestamp=created,
        symbol=f"S{index % 5}",
        series="EQ",
        identity_status="UNVERIFIED",
        feature_timestamp=feature_timestamp or created,
        recommendation="BUY",
        setup="BREAKOUT",
        entry_timing_state="BUY_NOW",
        approval_gate_states={"score": True},
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("102"),
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        outcome_horizon="20d",
        realised_outcome="PROFITABLE",
        mfe_pct=Decimal("4"),
        mae_pct=Decimal("-1"),
        realised_return_pct=realised_return,
        realised_r_multiple=realised_return / Decimal("5"),
        evidence_provenance={"source": "test"},
        replay_version="test-v1",
        data_quality_status="COMPLETE",
        corporate_action_status="UNAVAILABLE_NOT_LINKED",
        truth_class=HistoricalTruthClass.RECONSTRUCTED,
        features={
            "strategy_score": "80",
            "final_verdict": "BUY",
            "raw_approved": "true",
            "confidence": "HIGH",
            "data_quality": "COMPLETE",
            "setup_type": "BREAKOUT",
            "entry_timing_state": "BUY_NOW",
            "long_trade_permission": "true",
            "complete_trade_plan": "true",
            "entry_price": "102",
            "stop_distance_pct": "5",
            "reward_risk": "2",
            "price_component": "0.8",
            "volume_component": "0.7",
            "candle_component": "0.6",
        },
    )


def _strategy(threshold: str = "70") -> StrategySpecification:
    return StrategySpecification(
        strategy_version="STRATEGY_RESEARCH_V001",
        strategy_hash=f"hash-{threshold}",
        name="Score threshold",
        family=StrategyFamily.SCORE_THRESHOLD,
        conditions=(
            StrategyCondition(
                "strategy_score",
                ConditionOperator.GREATER_THAN_OR_EQUAL,
                threshold,
            ),
        ),
    )


def _passing_robustness() -> RobustnessResult:
    return RobustnessResult(
        strategy_version="STRATEGY_RESEARCH_V001",
        parameter_perturbation_passed=True,
        feature_ablation_passed=True,
        cost_stress_passed=True,
        delayed_entry_status="UNAVAILABLE",
        missed_fill_passed=True,
        stop_gap_status="UNAVAILABLE",
        bootstrap_expectancy_low_pct=Decimal("1"),
        bootstrap_expectancy_high_pct=Decimal("2"),
        fold_consistency_pct=Decimal("100"),
        symbol_concentration_pct=Decimal("10"),
        setup_concentration_pct=Decimal("10"),
        winner_concentration_pct=Decimal("10"),
        weaknesses=(),
    )


def _significant_test() -> MultipleTestingResult:
    return MultipleTestingResult(
        strategy_version="STRATEGY_RESEARCH_V001",
        raw_p_value=Decimal("0.001"),
        adjusted_p_value=Decimal("0.01"),
        hypotheses_tested=10,
        adjustment_method="BONFERRONI",
        statistically_significant=True,
    )


class _StaticSignalGenerator:
    def discovery_dataset(self) -> DiscoveryDataset:
        return _dataset(100)


def _service(tmp_path: Path) -> StrategyDiscoveryService:
    return StrategyDiscoveryService(
        signal_generator=cast(HistoricalSignalGenerator, _StaticSignalGenerator()),
        registry=StrategyRegistry(tmp_path / "strategy.json"),
        research_registry=ResearchExperimentRegistry(tmp_path / "research.json"),
    )
