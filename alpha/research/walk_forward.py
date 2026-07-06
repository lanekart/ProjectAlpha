"""Deterministic walk-forward research primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """Immutable train/test window using half-open observation indexes."""

    index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("window index cannot be negative")
        if self.train_start < 0:
            raise ValueError("train_start cannot be negative")
        if self.train_end <= self.train_start:
            raise ValueError("train_end must be greater than train_start")
        if self.test_start != self.train_end:
            raise ValueError("test_start must equal train_end")
        if self.test_end <= self.test_start:
            raise ValueError("test_end must be greater than test_start")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def train_size(self) -> int:
        """Return number of observations in the train slice."""

        return self.train_end - self.train_start

    @property
    def test_size(self) -> int:
        """Return number of observations in the test slice."""

        return self.test_end - self.test_start


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Immutable result for one walk-forward window."""

    window: WalkForwardWindow
    metrics: Mapping[str, Decimal]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.metrics) == 0:
            raise ValueError("walk-forward result requires at least one metric")

        copied_metrics: dict[str, Decimal] = {}
        for name, value in self.metrics.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("walk-forward metric name cannot be empty")
            copied_metrics[normalized_name] = value

        object.__setattr__(self, "metrics", MappingProxyType(copied_metrics))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Immutable aggregate walk-forward research report."""

    results: tuple[WalkForwardResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.results) == 0:
            raise ValueError("walk-forward report requires at least one result")

        expected_indexes = tuple(range(len(self.results)))
        actual_indexes = tuple(result.window.index for result in self.results)
        if actual_indexes != expected_indexes:
            raise ValueError("walk-forward results must be ordered by window index")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def window_count(self) -> int:
        """Return number of evaluated walk-forward windows."""

        return len(self.results)

    @property
    def metric_names(self) -> tuple[str, ...]:
        """Return sorted metric names present in the report."""

        names: set[str] = set()
        for result in self.results:
            names.update(result.metrics)
        return tuple(sorted(names))

    def average_metric(self, name: str) -> Decimal:
        """Return average value for a metric across all windows containing it."""

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("metric name cannot be empty")

        values = tuple(
            result.metrics[normalized_name]
            for result in self.results
            if normalized_name in result.metrics
        )
        if len(values) == 0:
            raise KeyError(f"unknown walk-forward metric: {normalized_name}")

        return sum(values, Decimal("0")) / Decimal(len(values))


@dataclass(frozen=True, slots=True)
class WalkForwardWindowGenerator:
    """Generate deterministic rolling or expanding walk-forward windows."""

    train_size: int
    test_size: int
    step_size: int = 1
    expanding: bool = False

    def __post_init__(self) -> None:
        if self.train_size <= 0:
            raise ValueError("train_size must be positive")
        if self.test_size <= 0:
            raise ValueError("test_size must be positive")
        if self.step_size <= 0:
            raise ValueError("step_size must be positive")

    def generate(self, observation_count: int) -> tuple[WalkForwardWindow, ...]:
        """Generate all complete windows for an observation count."""

        if observation_count <= 0:
            raise ValueError("observation_count must be positive")
        if observation_count < self.train_size + self.test_size:
            return ()

        windows: list[WalkForwardWindow] = []
        cursor = 0
        window_index = 0

        while True:
            train_start = 0 if self.expanding else cursor
            train_end = self.train_size + cursor
            test_start = train_end
            test_end = test_start + self.test_size

            if test_end > observation_count:
                break

            windows.append(
                WalkForwardWindow(
                    index=window_index,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    metadata={
                        "expanding": self.expanding,
                        "observation_count": observation_count,
                    },
                )
            )
            cursor += self.step_size
            window_index += 1

        return tuple(windows)


class WalkForwardEvaluator(Protocol):
    """Protocol for strategy-specific walk-forward evaluation adapters."""

    def evaluate(self, window: WalkForwardWindow) -> WalkForwardResult:
        """Evaluate one walk-forward window."""


@dataclass(frozen=True, slots=True)
class WalkForwardEngine:
    """Strategy-agnostic walk-forward research engine."""

    window_generator: WalkForwardWindowGenerator

    def run(
        self,
        *,
        observation_count: int,
        evaluator: WalkForwardEvaluator,
        metadata: Mapping[str, Any] | None = None,
    ) -> WalkForwardReport:
        """Evaluate all generated windows with the supplied evaluator."""

        windows = self.window_generator.generate(observation_count)
        if len(windows) == 0:
            raise ValueError("walk-forward run produced no complete windows")

        results = tuple(evaluator.evaluate(window) for window in windows)
        for expected_window, result in zip(windows, results, strict=True):
            if result.window != expected_window:
                raise ValueError("evaluator returned result for a different window")

        return WalkForwardReport(
            results=results,
            metadata={} if metadata is None else metadata,
        )
