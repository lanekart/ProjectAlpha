from decimal import Decimal

import pytest

from alpha.portfolio.optimizer_benchmark import (
    OptimizerBenchmarkMetric,
    OptimizerBenchmarkScenario,
    OptimizerBenchmarkService,
)
from alpha.portfolio.optimizer import OptimizationInput
from alpha.portfolio.optimizer_config import OptimizerConfig


def test_optimizer_benchmark_runs_configs_across_scenarios() -> None:
    service = OptimizerBenchmarkService()

    report = service.benchmark(
        configs=(
            OptimizerConfig(name="equal_weight"),
            OptimizerConfig(name="inverse_volatility"),
        ),
        scenarios=(
            OptimizerBenchmarkScenario(
                name="base",
                optimization_input=OptimizationInput(
                    universe=("AAPL", "MSFT"),
                    covariance={
                        "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                        "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.09")},
                    },
                ),
            ),
            OptimizerBenchmarkScenario(
                name="with_current_weights",
                optimization_input=OptimizationInput(
                    universe=("AAPL", "MSFT"),
                    current_weights={"AAPL": Decimal("0.80"), "MSFT": Decimal("0.20")},
                    covariance={
                        "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                        "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.09")},
                    },
                ),
            ),
        ),
        metadata={"suite": "unit"},
    )

    assert len(report.runs) == 4
    assert len(report.summaries) == 2
    assert report.metadata["suite"] == "unit"
    assert report.best_optimizer in {"equal_weight", "inverse_volatility"}
    assert report.summaries[0].average_score >= report.summaries[1].average_score


def test_optimizer_benchmark_records_diagnostics_and_metrics() -> None:
    service = OptimizerBenchmarkService()

    report = service.benchmark(
        configs=(OptimizerConfig(name="equal_weight"),),
        scenarios=(
            OptimizerBenchmarkScenario(
                name="cash",
                optimization_input=OptimizationInput(
                    universe=("AAPL", "MSFT"),
                    cash_reserve=Decimal("0.10"),
                ),
            ),
        ),
    )

    run = report.runs[0]

    assert run.optimizer == "equal_weight"
    assert run.scenario == "cash"
    assert run.metric_values["success"] == Decimal("1")
    assert run.metric_values["cash_drift"] == Decimal("0.00")
    assert run.diagnostics.cash_weight == Decimal("0.10")
    assert report.summaries[0].success_rate == Decimal("1")
    assert report.summaries[0].violation_rate == Decimal("0")


def test_optimizer_benchmark_supports_custom_metric_weights() -> None:
    service = OptimizerBenchmarkService(
        metrics=(OptimizerBenchmarkMetric("turnover", Decimal("2"), -1),)
    )

    report = service.benchmark(
        configs=(OptimizerConfig(name="equal_weight"),),
        scenarios=(
            OptimizerBenchmarkScenario(
                name="turnover",
                optimization_input=OptimizationInput(
                    universe=("AAPL", "MSFT"),
                    current_weights={"AAPL": Decimal("1"), "MSFT": Decimal("0")},
                ),
            ),
        ),
    )

    assert report.runs[0].metric_values["turnover"] == Decimal("0.5")
    assert report.runs[0].score == Decimal("-1.0")


def test_optimizer_benchmark_rejects_empty_inputs() -> None:
    service = OptimizerBenchmarkService()
    scenario = OptimizerBenchmarkScenario(
        name="base",
        optimization_input=OptimizationInput(universe=("AAPL",)),
    )

    with pytest.raises(ValueError, match="optimizer config"):
        service.benchmark(configs=(), scenarios=(scenario,))

    with pytest.raises(ValueError, match="scenario"):
        service.benchmark(configs=(OptimizerConfig(name="equal_weight"),), scenarios=())


def test_optimizer_benchmark_value_objects_validate_inputs() -> None:
    with pytest.raises(ValueError, match="scenario name"):
        OptimizerBenchmarkScenario(
            name=" ",
            optimization_input=OptimizationInput(universe=("AAPL",)),
        )

    with pytest.raises(ValueError, match="metric name"):
        OptimizerBenchmarkMetric(name=" ")

    with pytest.raises(ValueError, match="weight"):
        OptimizerBenchmarkMetric(name="success", weight=Decimal("-1"))

    with pytest.raises(ValueError, match="direction"):
        OptimizerBenchmarkMetric(name="success", direction=0)
