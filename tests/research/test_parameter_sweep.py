from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from alpha.research import (
    ParameterCombination,
    ParameterDefinition,
    ParameterGrid,
    ParameterSweepEngine,
    ParameterSweepReport,
    ParameterSweepResult,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
)


@dataclass(frozen=True, slots=True)
class StaticSweepEvaluator:
    def evaluate(self, combination: ParameterCombination) -> WalkForwardReport:
        lookback = combination.values["lookback"]
        threshold = combination.values["threshold"]
        if not isinstance(lookback, int):
            raise TypeError("lookback must be int")
        if not isinstance(threshold, Decimal):
            raise TypeError("threshold must be Decimal")

        score = Decimal(lookback) + threshold
        return WalkForwardReport(
            results=(
                WalkForwardResult(
                    window=WalkForwardWindow(
                        index=0,
                        train_start=0,
                        train_end=5,
                        test_start=5,
                        test_end=6,
                    ),
                    metrics={"score": score},
                ),
            )
        )


def test_parameter_grid_generates_deterministic_cartesian_product() -> None:
    grid = ParameterGrid(
        parameters=(
            ParameterDefinition(name="lookback", values=(10, 20)),
            ParameterDefinition(
                name="threshold",
                values=(Decimal("0.1"), Decimal("0.2")),
            ),
        )
    )

    combinations = grid.combinations()

    assert tuple(combination.values for combination in combinations) == (
        {"lookback": 10, "threshold": Decimal("0.1")},
        {"lookback": 10, "threshold": Decimal("0.2")},
        {"lookback": 20, "threshold": Decimal("0.1")},
        {"lookback": 20, "threshold": Decimal("0.2")},
    )
    assert tuple(combination.experiment_id for combination in combinations) == (
        "exp_0000__lookback-10__threshold-0p1",
        "exp_0001__lookback-10__threshold-0p2",
        "exp_0002__lookback-20__threshold-0p1",
        "exp_0003__lookback-20__threshold-0p2",
    )


def test_parameter_sweep_engine_ranks_higher_objective_first() -> None:
    grid = ParameterGrid(
        parameters=(
            ParameterDefinition(name="lookback", values=(10, 20)),
            ParameterDefinition(name="threshold", values=(Decimal("0.1"),)),
        )
    )
    engine = ParameterSweepEngine(objective_metric="score")

    report = engine.run(
        grid=grid,
        evaluator=StaticSweepEvaluator(),
        metadata={"suite": "unit"},
    )

    assert report.experiment_count == 2
    assert report.metadata["suite"] == "unit"
    assert report.best_result.combination.values["lookback"] == 20
    assert report.best_result.objective_value == Decimal("20.1")


def test_parameter_sweep_engine_supports_lower_is_better() -> None:
    grid = ParameterGrid(
        parameters=(
            ParameterDefinition(name="lookback", values=(10, 20)),
            ParameterDefinition(name="threshold", values=(Decimal("0.1"),)),
        )
    )
    engine = ParameterSweepEngine(objective_metric="score", higher_is_better=False)

    report = engine.run(grid=grid, evaluator=StaticSweepEvaluator())

    assert report.best_result.combination.values["lookback"] == 10
    assert report.best_result.objective_value == Decimal("10.1")


def test_parameter_sweep_engine_raises_for_missing_objective_metric() -> None:
    grid = ParameterGrid(
        parameters=(ParameterDefinition(name="lookback", values=(10,)),)
    )
    engine = ParameterSweepEngine(objective_metric="missing")

    with pytest.raises(KeyError, match="unknown walk-forward metric"):
        engine.run(grid=grid, evaluator=StaticSweepEvaluator())


def test_parameter_sweep_value_objects_validate_inputs() -> None:
    with pytest.raises(ValueError, match="parameter name"):
        ParameterDefinition(name=" ", values=(1,))

    with pytest.raises(ValueError, match="at least one value"):
        ParameterDefinition(name="lookback", values=())

    with pytest.raises(ValueError, match="duplicate values"):
        ParameterDefinition(name="lookback", values=(1, 1))

    with pytest.raises(ValueError, match="duplicate parameter names"):
        ParameterGrid(
            parameters=(
                ParameterDefinition(name="lookback", values=(1,)),
                ParameterDefinition(name="lookback", values=(2,)),
            )
        )

    with pytest.raises(ValueError, match="experiment_id"):
        ParameterCombination(experiment_id=" ", values={"lookback": 1})

    with pytest.raises(ValueError, match="objective_metric"):
        ParameterSweepEngine(objective_metric=" ")


def test_parameter_sweep_report_validates_objective_metric_consistency() -> None:
    combination = ParameterCombination(
        experiment_id="exp_0000__lookback-10",
        values={"lookback": 10},
    )
    walk_forward_report = WalkForwardReport(
        results=(
            WalkForwardResult(
                window=WalkForwardWindow(
                    index=0,
                    train_start=0,
                    train_end=5,
                    test_start=5,
                    test_end=6,
                ),
                metrics={"score": Decimal("1")},
            ),
        )
    )

    with pytest.raises(ValueError, match="report objective metric"):
        ParameterSweepReport(
            results=(
                ParameterSweepResult(
                    combination=combination,
                    report=walk_forward_report,
                    objective_metric="other",
                    objective_value=Decimal("1"),
                ),
            ),
            objective_metric="score",
        )
