from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from alpha.research import (
    WalkForwardEngine,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
    WalkForwardWindowGenerator,
)


@dataclass(frozen=True, slots=True)
class StaticEvaluator:
    metric_name: str = "return"

    def evaluate(self, window: WalkForwardWindow) -> WalkForwardResult:
        return WalkForwardResult(
            window=window,
            metrics={self.metric_name: Decimal(window.index + 1)},
            metadata={"source": "unit"},
        )


@dataclass(frozen=True, slots=True)
class MismatchedWindowEvaluator:
    def evaluate(self, window: WalkForwardWindow) -> WalkForwardResult:
        return WalkForwardResult(
            window=WalkForwardWindow(
                index=window.index,
                train_start=window.train_start,
                train_end=window.train_end + 1,
                test_start=window.train_end + 1,
                test_end=window.test_end + 1,
            ),
            metrics={"return": Decimal("1")},
        )


def test_rolling_window_generator_creates_complete_windows() -> None:
    generator = WalkForwardWindowGenerator(
        train_size=3,
        test_size=2,
        step_size=2,
    )

    windows = generator.generate(observation_count=9)

    assert windows == (
        WalkForwardWindow(
            index=0,
            train_start=0,
            train_end=3,
            test_start=3,
            test_end=5,
            metadata={"expanding": False, "observation_count": 9},
        ),
        WalkForwardWindow(
            index=1,
            train_start=2,
            train_end=5,
            test_start=5,
            test_end=7,
            metadata={"expanding": False, "observation_count": 9},
        ),
        WalkForwardWindow(
            index=2,
            train_start=4,
            train_end=7,
            test_start=7,
            test_end=9,
            metadata={"expanding": False, "observation_count": 9},
        ),
    )


def test_expanding_window_generator_keeps_train_start_fixed() -> None:
    generator = WalkForwardWindowGenerator(
        train_size=3,
        test_size=2,
        step_size=2,
        expanding=True,
    )

    windows = generator.generate(observation_count=9)

    assert tuple(window.train_start for window in windows) == (0, 0, 0)
    assert tuple(window.train_end for window in windows) == (3, 5, 7)
    assert tuple(window.test_end for window in windows) == (5, 7, 9)


def test_window_generator_returns_empty_when_data_is_insufficient() -> None:
    generator = WalkForwardWindowGenerator(train_size=5, test_size=2)

    assert generator.generate(observation_count=6) == ()


def test_walk_forward_engine_runs_evaluator_for_each_window() -> None:
    engine = WalkForwardEngine(
        window_generator=WalkForwardWindowGenerator(
            train_size=2,
            test_size=1,
            step_size=1,
        )
    )

    report = engine.run(
        observation_count=5,
        evaluator=StaticEvaluator(),
        metadata={"experiment": "walk-forward"},
    )

    assert report.window_count == 3
    assert report.metric_names == ("return",)
    assert report.average_metric("return") == Decimal("2")
    assert report.metadata["experiment"] == "walk-forward"
    assert tuple(result.window.index for result in report.results) == (0, 1, 2)


def test_walk_forward_engine_rejects_no_complete_windows() -> None:
    engine = WalkForwardEngine(
        window_generator=WalkForwardWindowGenerator(train_size=5, test_size=2)
    )

    with pytest.raises(ValueError, match="no complete windows"):
        engine.run(observation_count=6, evaluator=StaticEvaluator())


def test_walk_forward_engine_enforces_evaluator_window_contract() -> None:
    engine = WalkForwardEngine(
        window_generator=WalkForwardWindowGenerator(train_size=2, test_size=1)
    )

    with pytest.raises(ValueError, match="different window"):
        engine.run(observation_count=3, evaluator=MismatchedWindowEvaluator())


def test_walk_forward_report_rejects_unordered_results() -> None:
    first = WalkForwardResult(
        window=WalkForwardWindow(
            index=1,
            train_start=0,
            train_end=2,
            test_start=2,
            test_end=3,
        ),
        metrics={"return": Decimal("1")},
    )

    with pytest.raises(ValueError, match="ordered by window index"):
        WalkForwardReport(results=(first,))


def test_walk_forward_values_validate_inputs() -> None:
    with pytest.raises(ValueError, match="window index"):
        WalkForwardWindow(
            index=-1,
            train_start=0,
            train_end=2,
            test_start=2,
            test_end=3,
        )

    with pytest.raises(ValueError, match="train_size"):
        WalkForwardWindowGenerator(train_size=0, test_size=1)

    with pytest.raises(ValueError, match="metric name"):
        WalkForwardResult(
            window=WalkForwardWindow(
                index=0,
                train_start=0,
                train_end=2,
                test_start=2,
                test_end=3,
            ),
            metrics={" ": Decimal("1")},
        )


def test_walk_forward_report_rejects_unknown_metric() -> None:
    report = WalkForwardReport(
        results=(
            WalkForwardResult(
                window=WalkForwardWindow(
                    index=0,
                    train_start=0,
                    train_end=2,
                    test_start=2,
                    test_end=3,
                ),
                metrics={"return": Decimal("1")},
            ),
        )
    )

    with pytest.raises(KeyError, match="unknown walk-forward metric"):
        report.average_metric("sharpe")
