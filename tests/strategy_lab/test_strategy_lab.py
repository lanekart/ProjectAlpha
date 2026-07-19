from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.strategy_lab_cli import strategy_lab_app
from alpha.recommendation_intelligence.models import OHLCVBar
from alpha.research.diagnostic_registry import default_diagnostic_registry
from alpha.research.models import ResearchSubsystem
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.models import (
    ConditionOperator,
    DiscoveryDataset,
    DiscoveryRow,
    HistoricalTruthClass,
    StrategyCondition,
)
from alpha.strategy_lab.backtest_engine import StrategyLabBacktestEngine
from alpha.strategy_lab.combination_attribution import CombinationAttributionEngine
from alpha.strategy_lab.combination_generator import (
    CombinationGenerator,
    GenerationRequest,
)
from alpha.strategy_lab.component_attribution import ComponentAttributionEngine
from alpha.strategy_lab.execution_assumptions import default_execution_profile
from alpha.strategy_lab.experiment_registry import StrategyLabExperimentRegistry
from alpha.strategy_lab.indicator_registry import IndicatorRegistry
from alpha.strategy_lab.leaderboard import StrategyLeaderboard
from alpha.strategy_lab.models import (
    AttributionClassification,
    EntryRule,
    EvidenceLabel,
    LabEvidenceClass,
    LabStrategySpecification,
    LeaderboardView,
    StopRule,
    StrategyClassification,
    TargetRule,
    TradeExitReason,
    TradeSimulationRequest,
)
from alpha.strategy_lab.performance_metrics import PerformanceMetricsEngine
from alpha.strategy_lab.rendering import render_report
from alpha.strategy_lab.service import StrategyLabService
from alpha.strategy_lab.strategy_comparison import StrategyComparisonEngine
from alpha.strategy_lab.strategy_template_registry import StrategyTemplateRegistry
from alpha.strategy_lab.trade_simulator import TradeSimulator


def test_indicator_registry_excludes_quarantined_features() -> None:
    registry = IndicatorRegistry()

    assert len(registry.definitions) == 21
    assert "price_component" in {item.canonical_id for item in registry.usable}
    assert "market_regime" not in {item.canonical_id for item in registry.usable}
    with pytest.raises(ValueError, match="quarantined"):
        registry.require_usable("market_regime")


def test_strategy_template_inventory_is_complete_and_interpretable() -> None:
    templates = StrategyTemplateRegistry().templates

    assert len(templates) == 17
    assert {item.template_id for item in templates} >= {
        "single-indicator",
        "price-volume",
        "approval-v1",
        "no-trade",
    }


def test_generator_is_bounded_deterministic_and_rejects_quarantine() -> None:
    dataset = _dataset(tuple(_row(index, Decimal("1")) for index in range(40)))
    generator = CombinationGenerator()
    profile = _profile()

    first, first_manifest = generator.generate(
        dataset=dataset,
        request=GenerationRequest(maximum_components=3),
        execution_profile=profile,
    )
    second, second_manifest = generator.generate(
        dataset=dataset,
        request=GenerationRequest(maximum_components=3),
        execution_profile=profile,
    )

    assert first == second
    assert first_manifest.search_space_hash == second_manifest.search_space_hash
    assert all(len(item.conditions) <= 3 or item.benchmark for item in first)
    assert len({item.strategy_hash for item in first}) == len(first)
    with pytest.raises(ValueError, match="quarantined"):
        generator.generate(
            dataset=dataset,
            request=GenerationRequest(indicators=("market_regime",)),
            execution_profile=profile,
        )
    with pytest.raises(ValueError, match="between 1 and 5"):
        generator.generate(
            dataset=dataset,
            request=GenerationRequest(maximum_components=6),
            execution_profile=profile,
        )


def test_point_in_time_row_rejects_future_feature_timestamp() -> None:
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="feature timestamp"):
        _row(
            1,
            Decimal("1"),
            candidate_timestamp=timestamp,
            feature_timestamp=timestamp + timedelta(days=1),
        )


def test_trade_simulator_confirmation_entry_and_target() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(
            bars=(
                _bar(1, "99", "101", "98", "100"),
                _bar(2, "102", "111", "99", "110"),
            )
        ),
        _profile(),
    )

    assert simulation.entered is True
    assert simulation.entry_price == Decimal("100")
    assert simulation.exit_reason is TradeExitReason.TARGET_1
    assert simulation.gross_return_pct == Decimal("10.00")


def test_trade_simulator_missed_entry_is_explicit() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(
            confirmation_entry=Decimal("120"),
            bars=(_bar(1, "99", "101", "98", "100"),),
        ),
        _profile(),
    )

    assert simulation.entered is False
    assert simulation.exit_reason is TradeExitReason.NOT_ENTERED
    assert simulation.missed_trade_reason is not None


def test_same_bar_stop_and_target_uses_conservative_stop_first() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(bars=(_bar(1, "100", "111", "94", "105"),)),
        _profile(),
    )

    assert simulation.exit_reason is TradeExitReason.STOP
    assert simulation.exit_price == Decimal("95")
    assert simulation.ambiguity_count == 1


def test_gap_through_stop_fills_at_open() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(
            bars=(
                _bar(1, "100", "101", "98", "100"),
                _bar(2, "90", "100", "89", "95"),
            )
        ),
        _profile(),
    )

    assert simulation.exit_reason is TradeExitReason.STOP
    assert simulation.exit_price == Decimal("90")


def test_partial_exit_and_runner_are_simulated() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(
            target_rule=TargetRule.PARTIAL_THEN_RUNNER,
            bars=(
                _bar(1, "100", "101", "98", "100"),
                _bar(2, "105", "111", "101", "109"),
                _bar(3, "112", "121", "110", "120"),
            ),
        ),
        _profile(),
    )

    assert simulation.partial_exit_fraction == Decimal("0.50")
    assert simulation.exit_reason is TradeExitReason.TARGET_2
    assert simulation.gross_return_pct == Decimal("15.00")


def test_trailing_stop_and_time_exit_are_supported() -> None:
    trailing = TradeSimulator().simulate(
        _trade_request(
            target_rule=TargetRule.TRAILING_AFTER_TARGET_1,
            bars=(
                _bar(1, "100", "101", "98", "100"),
                _bar(2, "105", "111", "101", "110"),
                _bar(3, "112", "117", "111", "115"),
                _bar(4, "110", "112", "109", "110"),
            ),
        ),
        _profile(),
    )
    timed = TradeSimulator().simulate(
        _trade_request(
            target_rule=TargetRule.TIME_EXIT,
            bars=(
                _bar(1, "100", "101", "98", "100"),
                _bar(2, "101", "104", "99", "103"),
            ),
        ),
        _profile(),
    )

    assert trailing.exit_reason is TradeExitReason.TRAILING_STOP
    assert timed.exit_reason is TradeExitReason.TIME_EXIT


def test_transaction_cost_and_slippage_reduce_net_return() -> None:
    simulation = TradeSimulator().simulate(
        _trade_request(
            bars=(
                _bar(1, "100", "101", "98", "100"),
                _bar(2, "102", "111", "99", "110"),
            )
        ),
        default_execution_profile(cost_bps=Decimal("20"), slippage_bps=Decimal("10")),
    )

    assert simulation.costs_pct == Decimal("0.3")
    assert simulation.net_return_pct == Decimal("9.70")


def test_performance_metrics_cover_trade_risk_and_portfolio_statistics() -> None:
    rows = (
        _row(0, Decimal("10")),
        _row(1, Decimal("-5")),
        _row(2, Decimal("5")),
        _row(3, Decimal("-2")),
    )
    metrics = PerformanceMetricsEngine().evaluate(
        strategy=_strategy("all", "50"),
        rows=rows,
        profile=_profile(),
    )

    assert metrics.average_winner_pct == Decimal("7.50")
    assert metrics.average_loser_pct == Decimal("-3.50")
    assert metrics.payoff_ratio == Decimal("2.14")
    assert metrics.expectancy_pct == Decimal("2.00")
    assert metrics.precision_pct == Decimal("50.00")
    assert metrics.precision_ci_low_pct is not None
    assert metrics.profit_factor == Decimal("2.14")
    assert metrics.maximum_drawdown_pct is not None
    assert metrics.sharpe_ratio is not None
    assert metrics.sortino_ratio is not None
    assert metrics.capital_utilisation_pct == Decimal("100.00")


def test_yearly_quarterly_and_rolling_metrics_are_generated() -> None:
    rows = tuple(_row(index, Decimal("1")) for index in range(60))
    run = StrategyLabBacktestEngine().run(
        dataset=_dataset(rows),
        strategies=(_strategy("all", "50"),),
        profile=_profile(),
    )
    timeline = run.results[0].timeline

    assert timeline.annual
    assert timeline.quarterly
    assert len(timeline.rolling_20) == 41
    assert len(timeline.rolling_50) == 11
    assert len(timeline.equity_curve) == 60


def test_sample_multiplier_prevents_tiny_sample_from_leading_default_rank() -> None:
    rows = tuple(
        _row(
            index,
            (
                Decimal("10")
                if index < 10
                else Decimal("-1")
                if index % 3 == 0
                else Decimal("2")
            ),
            score=Decimal("95") if index < 10 else Decimal("70"),
        )
        for index in range(40)
    )
    run = StrategyLabBacktestEngine().run(
        dataset=_dataset(rows),
        strategies=(
            _strategy("tiny", "90"),
            _strategy("broad", "50"),
        ),
        profile=_profile(),
    )
    ranked = StrategyLeaderboard().rank(run.results)
    precision_ranked = StrategyLeaderboard().rank(
        run.results, view=LeaderboardView.PRECISION
    )

    assert ranked[0].strategy.strategy_id == "broad"
    assert precision_ranked[0].strategy.strategy_id == "tiny"
    assert precision_ranked[0].evidence_label is EvidenceLabel.INSUFFICIENT_SAMPLE


def test_component_and_combination_attribution_flag_lineage_and_concentration() -> None:
    rows = tuple(_row(index, Decimal("2")) for index in range(40))
    base = _strategy(
        "price",
        "50",
        family="SIMPLE_CONJUNCTION",
        extra=(
            StrategyCondition(
                "price_component",
                ConditionOperator.GREATER_THAN_OR_EQUAL,
                "0.50",
            ),
        ),
    )
    combination = replace(
        base,
        strategy_id="price-volume",
        strategy_hash="hash-price-volume",
        conditions=(
            *base.conditions,
            StrategyCondition(
                "volume_component",
                ConditionOperator.GREATER_THAN_OR_EQUAL,
                "0.50",
            ),
        ),
    )
    run = StrategyLabBacktestEngine().run(
        dataset=_dataset(rows),
        strategies=(base, combination),
        profile=_profile(),
    )
    attribution = ComponentAttributionEngine().analyze(run.results)
    combinations = CombinationAttributionEngine().analyze(
        run.results, population_count=40
    )

    volume = next(
        item for item in attribution if item.component_id == "volume_component"
    )
    assert volume.classification is AttributionClassification.LINEAGE_CONFOUNDED
    assert combinations


def test_reconstructed_results_never_become_deployable() -> None:
    rows = tuple(_row(index, Decimal("3")) for index in range(40))
    result = (
        StrategyLabBacktestEngine()
        .run(
            dataset=_dataset(rows),
            strategies=(_strategy("all", "50"),),
            profile=_profile(),
        )
        .results[0]
    )

    assert result.evidence_label is EvidenceLabel.RECONSTRUCTED_RESEARCH_ONLY
    assert result.classification not in {
        StrategyClassification.WALK_FORWARD_CANDIDATE,
        StrategyClassification.SHADOW_VALIDATION_CANDIDATE,
    }


def test_strategy_comparison_uses_shared_population_and_exact_rules() -> None:
    rows = tuple(_row(index, Decimal("2")) for index in range(40))
    run = StrategyLabBacktestEngine().run(
        dataset=_dataset(rows),
        strategies=(_strategy("a", "50"), _strategy("b", "70")),
        profile=_profile(),
    )
    comparison = StrategyComparisonEngine().compare(
        run.results, ("a", "b"), shared_population=40
    )

    assert comparison.shared_population == 40
    assert comparison.rule_definitions["a"]
    assert comparison.evidence_confidence == "LOW_RECONSTRUCTED"


def test_registry_is_immutable_idempotent_and_exports_json_csv(tmp_path: Path) -> None:
    report = _service(tmp_path).report(persist=False)
    registry = StrategyLabExperimentRegistry(tmp_path / "lab.json")

    assert registry.record(report) is True
    assert registry.record(report) is False
    with pytest.raises(ValueError, match="immutable"):
        registry.record(replace(report, final_conclusion="ALTERED"))
    assert registry.export_json(tmp_path / "lab-export.json").exists()
    csv_path = registry.export_csv(tmp_path / "lab-export.csv")
    assert "production_influence" in csv_path.read_text(encoding="utf-8")


def test_service_records_research_experiment_and_renders_report(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report = service.report()
    experiments = ResearchExperimentRegistry(tmp_path / "research.json").load()

    assert report.final_conclusion == "NO_RELIABLE_STRATEGY_FOUND"
    assert experiments[-1].subsystem is ResearchSubsystem.STRATEGY_LAB
    assert "PRODUCTION_INFLUENCE=false" in "\n".join(render_report(report))


def test_robustness_records_multiple_testing_and_cost_stress() -> None:
    rows = tuple(_row(index, Decimal("3")) for index in range(40))
    result = (
        StrategyLabBacktestEngine()
        .run(
            dataset=_dataset(rows),
            strategies=(_strategy("all", "50"),),
            profile=default_execution_profile(
                cost_bps=Decimal("20"), slippage_bps=Decimal("10")
            ),
        )
        .results[0]
    )

    assert result.robustness is not None
    assert result.robustness.hypotheses_tested == 1
    assert result.robustness.adjusted_p_value is not None
    assert result.robustness.cost_stress_passed is True


def test_ird_discovers_strategy_lab_without_core_changes() -> None:
    registry = default_diagnostic_registry(discover_plugins=False)

    assert "strategy-indicator-backtest-lab" in registry.plugin_ids


def test_cli_registration_and_inventory_rendering() -> None:
    commands = {item.name for item in strategy_lab_app.registered_commands}
    assert commands == {
        "inventory",
        "generate",
        "backtest",
        "leaderboard",
        "compare",
        "attribution",
        "timeline",
        "robustness",
        "report",
    }
    result = CliRunner().invoke(strategy_lab_app, ["inventory"])

    assert result.exit_code == 0
    assert "Strategy Lab Indicator and Rule Inventory" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_strategy_model_rejects_production_influence() -> None:
    with pytest.raises(ValueError, match="cannot influence production"):
        replace(_strategy("forbidden", "50"), production_influence=True)


class _SignalGenerator:
    def __init__(self, dataset: DiscoveryDataset) -> None:
        self.dataset = dataset

    def discovery_dataset(self) -> DiscoveryDataset:
        return self.dataset


def _service(tmp_path: Path) -> StrategyLabService:
    dataset = _dataset(tuple(_row(index, Decimal("2")) for index in range(40)))
    return StrategyLabService(
        signal_generator=_SignalGenerator(dataset),  # type: ignore[arg-type]
        experiment_registry=StrategyLabExperimentRegistry(tmp_path / "lab.json"),
        research_registry=ResearchExperimentRegistry(tmp_path / "research.json"),
    )


def _profile():
    return default_execution_profile(cost_bps=Decimal("0"), slippage_bps=Decimal("0"))


def _strategy(
    strategy_id: str,
    threshold: str,
    *,
    family: str = "SCORE_THRESHOLD",
    extra: tuple[StrategyCondition, ...] = (),
) -> LabStrategySpecification:
    conditions = (
        StrategyCondition(
            "strategy_score",
            ConditionOperator.GREATER_THAN_OR_EQUAL,
            threshold,
        ),
        *extra,
    )
    return LabStrategySpecification(
        strategy_id=strategy_id,
        strategy_hash=f"hash-{strategy_id}",
        source_strategy_version="STRATEGY_RESEARCH_V001",
        name=strategy_id,
        family=family,
        conditions=conditions,
        entry_rule=EntryRule.RECORDED_REFERENCE,
        stop_rule=StopRule.RECORDED_PLAN,
        target_rule=TargetRule.RECORDED_PLAN,
        holding_period_days=20,
        execution_profile_id="TEST",
        dataset_version="test-dataset",
        evidence_class=LabEvidenceClass.RECONSTRUCTED,
        benchmark=False,
    )


def _dataset(rows: tuple[DiscoveryRow, ...]) -> DiscoveryDataset:
    return DiscoveryDataset(
        dataset_version="test-reconstructed-v1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        source_hash="source-hash",
        population_class=HistoricalTruthClass.RECONSTRUCTED,
        rows=rows,
        exclusions=(),
        quarantined_population=0,
    )


def _row(
    index: int,
    realised: Decimal,
    *,
    score: Decimal = Decimal("80"),
    candidate_timestamp: datetime | None = None,
    feature_timestamp: datetime | None = None,
) -> DiscoveryRow:
    timestamp = candidate_timestamp or datetime(2020, 1, 1, tzinfo=UTC) + timedelta(
        days=index * 30
    )
    return DiscoveryRow(
        candidate_id=f"candidate-{index}",
        candidate_timestamp=timestamp,
        symbol=f"S{index % 5}",
        series="EQ",
        identity_status="RECONSTRUCTED",
        feature_timestamp=feature_timestamp or timestamp,
        recommendation="BUY",
        setup="MOMENTUM",
        entry_timing_state="ENTRY_READY",
        approval_gate_states={"gate": index % 2 == 0},
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("100"),
        confirmation_entry=Decimal("101"),
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        outcome_horizon="20D",
        realised_outcome="PROFITABLE" if realised > 0 else "UNPROFITABLE",
        mfe_pct=max(Decimal("0"), realised + Decimal("2")),
        mae_pct=min(Decimal("0"), realised - Decimal("2")),
        realised_return_pct=realised,
        realised_r_multiple=realised / Decimal("5"),
        evidence_provenance={"source": "test"},
        replay_version="test-v1",
        data_quality_status="COMPLETE",
        corporate_action_status="UNAVAILABLE_NOT_LINKED",
        truth_class=HistoricalTruthClass.RECONSTRUCTED,
        features={
            "strategy_score": str(score),
            "final_verdict": "BUY",
            "raw_approved": "true" if index % 3 == 0 else "false",
            "confidence": "HIGH",
            "data_quality": "COMPLETE",
            "setup_type": "MOMENTUM",
            "entry_timing_state": "ENTRY_READY",
            "long_trade_permission": "true",
            "complete_trade_plan": "true",
            "entry_price": "101",
            "stop_distance_pct": "5",
            "reward_risk": "2",
            "price_component": "0.70",
            "volume_component": "0.60",
            "candle_component": "0.50",
        },
    )


def _trade_request(
    *,
    bars: tuple[OHLCVBar, ...],
    confirmation_entry: Decimal = Decimal("100"),
    target_rule: TargetRule = TargetRule.RECORDED_PLAN,
) -> TradeSimulationRequest:
    return TradeSimulationRequest(
        recommendation_id="rec-1",
        symbol="AAA",
        decision_time=datetime(2025, 1, 1, tzinfo=UTC),
        bars=bars,
        entry_rule=EntryRule.CONFIRMATION_ENTRY,
        stop_rule=StopRule.RECORDED_PLAN,
        target_rule=target_rule,
        confirmation_entry=confirmation_entry,
        recorded_stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("120"),
        target_3=Decimal("130"),
        atr=Decimal("2"),
        holding_period_days=20,
    )


def _bar(
    day: int,
    open_price: str,
    high: str,
    low: str,
    close: str,
) -> OHLCVBar:
    return OHLCVBar(
        observed_on=date(2025, 1, day + 1),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100000"),
    )
