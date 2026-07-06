"""Deterministic optimizer benchmarking framework."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from alpha.portfolio.optimization_diagnostics import OptimizationDiagnostics
from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.optimizer_factory import OptimizerFactory


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkScenario:
    """Immutable optimizer benchmark scenario."""

    name: str
    optimization_input: OptimizationInput
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("benchmark scenario name cannot be empty")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkMetric:
    """Weighted benchmark metric definition.

    Positive direction rewards larger values. Negative direction rewards smaller
    values. Metric extraction is intentionally limited to deterministic values
    already produced by optimization results and diagnostics.
    """

    name: str
    weight: Decimal = Decimal("1")
    direction: int = 1

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("benchmark metric name cannot be empty")
        if self.weight < Decimal("0"):
            raise ValueError("benchmark metric weight cannot be negative")
        if self.direction not in {-1, 1}:
            raise ValueError("benchmark metric direction must be -1 or 1")

        object.__setattr__(self, "name", normalized_name)


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkRun:
    """Single optimizer benchmark run for one scenario."""

    optimizer: str
    scenario: str
    result: OptimizationResult
    diagnostics: OptimizationDiagnostics
    metric_values: Mapping[str, Decimal]
    score: Decimal

    def __post_init__(self) -> None:
        normalized_optimizer = self.optimizer.strip()
        normalized_scenario = self.scenario.strip()
        if not normalized_optimizer:
            raise ValueError("benchmark run optimizer cannot be empty")
        if not normalized_scenario:
            raise ValueError("benchmark run scenario cannot be empty")

        object.__setattr__(self, "optimizer", normalized_optimizer)
        object.__setattr__(self, "scenario", normalized_scenario)
        object.__setattr__(
            self,
            "metric_values",
            MappingProxyType(dict(self.metric_values)),
        )


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkSummary:
    """Aggregate benchmark summary for one optimizer."""

    optimizer: str
    runs: tuple[OptimizerBenchmarkRun, ...]
    average_score: Decimal
    success_rate: Decimal
    violation_rate: Decimal
    average_turnover: Decimal

    def __post_init__(self) -> None:
        normalized_optimizer = self.optimizer.strip()
        if not normalized_optimizer:
            raise ValueError("benchmark summary optimizer cannot be empty")
        if len(self.runs) == 0:
            raise ValueError("benchmark summary requires at least one run")
        if self.success_rate < Decimal("0") or self.success_rate > Decimal("1"):
            raise ValueError("success_rate must be between 0 and 1")
        if self.violation_rate < Decimal("0") or self.violation_rate > Decimal("1"):
            raise ValueError("violation_rate must be between 0 and 1")
        if self.average_turnover < Decimal("0"):
            raise ValueError("average_turnover cannot be negative")

        object.__setattr__(self, "optimizer", normalized_optimizer)


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkReport:
    """Complete deterministic optimizer benchmark report."""

    runs: tuple[OptimizerBenchmarkRun, ...]
    summaries: tuple[OptimizerBenchmarkSummary, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.runs) == 0:
            raise ValueError("benchmark report requires at least one run")
        if len(self.summaries) == 0:
            raise ValueError("benchmark report requires at least one summary")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def best_optimizer(self) -> str:
        """Return the highest-scoring optimizer name."""

        return self.summaries[0].optimizer


@dataclass(frozen=True, slots=True)
class OptimizerBenchmarkService:
    """Benchmark multiple optimizer configurations across scenarios."""

    factory: OptimizerFactory = field(default_factory=OptimizerFactory)
    metrics: tuple[OptimizerBenchmarkMetric, ...] = (
        OptimizerBenchmarkMetric("success", Decimal("10"), 1),
        OptimizerBenchmarkMetric("violations", Decimal("5"), -1),
        OptimizerBenchmarkMetric("turnover", Decimal("1"), -1),
        OptimizerBenchmarkMetric("cash_drift", Decimal("1"), -1),
    )

    def benchmark(
        self,
        *,
        configs: Sequence[OptimizerConfig],
        scenarios: Sequence[OptimizerBenchmarkScenario],
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizerBenchmarkReport:
        """Run benchmark and return ranked aggregate report."""

        if len(configs) == 0:
            raise ValueError("benchmark requires at least one optimizer config")
        if len(scenarios) == 0:
            raise ValueError("benchmark requires at least one scenario")

        runs: list[OptimizerBenchmarkRun] = []
        for config in configs:
            optimizer = self.factory.create(config)
            for scenario in scenarios:
                result = optimizer.optimize(scenario.optimization_input)
                diagnostics = OptimizationDiagnostics.from_optimization(
                    optimization_input=scenario.optimization_input,
                    result=result,
                )
                metric_values = self._metric_values(
                    result=result,
                    diagnostics=diagnostics,
                    optimization_input=scenario.optimization_input,
                )
                runs.append(
                    OptimizerBenchmarkRun(
                        optimizer=optimizer.name,
                        scenario=scenario.name,
                        result=result,
                        diagnostics=diagnostics,
                        metric_values=metric_values,
                        score=self._score(metric_values),
                    )
                )

        summaries = self._summaries(runs)
        return OptimizerBenchmarkReport(
            runs=tuple(runs),
            summaries=summaries,
            metadata={} if metadata is None else metadata,
        )

    def _metric_values(
        self,
        *,
        result: OptimizationResult,
        diagnostics: OptimizationDiagnostics,
        optimization_input: OptimizationInput,
    ) -> Mapping[str, Decimal]:
        expected_cash = optimization_input.cash_reserve
        cash_drift = abs(result.cash_weight - expected_cash)
        return {
            "success": Decimal("1") if result.success else Decimal("0"),
            "violations": Decimal(len(result.constraint_violations)),
            "turnover": diagnostics.expected_turnover,
            "cash_drift": cash_drift,
        }

    def _score(self, metric_values: Mapping[str, Decimal]) -> Decimal:
        score = Decimal("0")
        for metric in self.metrics:
            value = metric_values.get(metric.name, Decimal("0"))
            score += value * metric.weight * Decimal(metric.direction)
        return score

    def _summaries(
        self,
        runs: Iterable[OptimizerBenchmarkRun],
    ) -> tuple[OptimizerBenchmarkSummary, ...]:
        grouped: dict[str, list[OptimizerBenchmarkRun]] = {}
        for run in runs:
            grouped.setdefault(run.optimizer, []).append(run)

        summaries = tuple(
            self._summary(optimizer=optimizer, runs=tuple(optimizer_runs))
            for optimizer, optimizer_runs in grouped.items()
        )
        return tuple(
            sorted(
                summaries,
                key=lambda summary: (
                    summary.average_score,
                    summary.success_rate,
                    summary.optimizer,
                ),
                reverse=True,
            )
        )

    def _summary(
        self,
        *,
        optimizer: str,
        runs: tuple[OptimizerBenchmarkRun, ...],
    ) -> OptimizerBenchmarkSummary:
        run_count = Decimal(len(runs))
        average_score = sum((run.score for run in runs), Decimal("0")) / run_count
        success_rate = (
            sum((Decimal("1") for run in runs if run.result.success), Decimal("0"))
            / run_count
        )
        violation_rate = (
            sum(
                (Decimal("1") for run in runs if run.result.has_violations),
                Decimal("0"),
            )
            / run_count
        )
        average_turnover = (
            sum((run.result.expected_turnover for run in runs), Decimal("0"))
            / run_count
        )

        return OptimizerBenchmarkSummary(
            optimizer=optimizer,
            runs=runs,
            average_score=average_score,
            success_rate=success_rate,
            violation_rate=violation_rate,
            average_turnover=average_turnover,
        )
