from decimal import Decimal

import pytest

from alpha.research import (
    ResearchExperimentManifest,
    ResearchExperimentRecord,
    ResearchSession,
    ResearchSessionEntry,
    StrategyComparisonEngine,
    StrategyComparisonReport,
    StrategyComparisonResult,
)


def make_manifest(
    *,
    run_id: str,
    objective_value: Decimal,
    objective_metric: str = "score",
    parameter_name: str = "lookback",
    parameter_value: int = 20,
) -> ResearchExperimentManifest:
    return ResearchExperimentManifest(
        run_id=run_id,
        objective_metric=objective_metric,
        records=(
            ResearchExperimentRecord(
                experiment_id=f"{run_id}-best",
                parameters={parameter_name: parameter_value},
                objective_metric=objective_metric,
                objective_value=objective_value,
                rank=1,
            ),
        ),
    )


def make_session() -> ResearchSession:
    return ResearchSession(
        session_id="session-1",
        name="Momentum comparison",
        entries=(
            ResearchSessionEntry(
                label="baseline",
                strategy_name="momentum",
                manifest=make_manifest(
                    run_id="run-1",
                    objective_value=Decimal("1.10"),
                    parameter_value=20,
                ),
            ),
            ResearchSessionEntry(
                label="candidate",
                strategy_name="breakout",
                manifest=make_manifest(
                    run_id="run-2",
                    objective_value=Decimal("1.40"),
                    parameter_value=55,
                ),
            ),
            ResearchSessionEntry(
                label="defensive",
                strategy_name="momentum",
                manifest=make_manifest(
                    run_id="run-3",
                    objective_value=Decimal("0.90"),
                    parameter_value=10,
                ),
            ),
        ),
    )


def test_strategy_comparison_engine_ranks_session_entries() -> None:
    report = StrategyComparisonEngine(objective_metric="score").compare(
        session=make_session()
    )

    assert report.session_id == "session-1"
    assert report.objective_metric == "score"
    assert report.result_count == 3
    assert report.strategy_count == 2
    assert report.best_result.label == "candidate"
    assert report.best_result.strategy_name == "breakout"
    assert report.best_result.objective_value == Decimal("1.40")
    assert tuple(result.comparison_rank for result in report.results) == (1, 2, 3)


def test_strategy_comparison_engine_supports_lower_is_better() -> None:
    report = StrategyComparisonEngine(
        objective_metric="score",
        higher_is_better=False,
    ).compare(session=make_session())

    assert report.best_result.label == "defensive"
    assert report.best_result.objective_value == Decimal("0.90")


def test_strategy_comparison_report_filters_results_by_strategy() -> None:
    report = StrategyComparisonEngine(objective_metric="score").compare(
        session=make_session(),
        metadata={"owner": "research"},
    )

    momentum_results = report.results_for_strategy("momentum")

    assert tuple(result.label for result in momentum_results) == (
        "baseline",
        "defensive",
    )
    assert report.metadata["owner"] == "research"


def test_strategy_comparison_report_exposes_objective_values_by_label() -> None:
    report = StrategyComparisonEngine(objective_metric="score").compare(
        session=make_session()
    )

    assert report.objective_values() == {
        "candidate": Decimal("1.40"),
        "baseline": Decimal("1.10"),
        "defensive": Decimal("0.90"),
    }


def test_strategy_comparison_result_copies_and_validates_inputs() -> None:
    result = StrategyComparisonResult(
        strategy_name=" momentum ",
        label=" baseline ",
        run_id=" run-1 ",
        objective_metric=" score ",
        objective_value=Decimal("1.10"),
        source_rank=1,
        comparison_rank=2,
        parameters={" lookback ": 20},
        metadata={" suite ": "unit"},
    )

    assert result.strategy_name == "momentum"
    assert result.label == "baseline"
    assert result.run_id == "run-1"
    assert result.objective_metric == "score"
    assert result.parameters == {"lookback": 20}
    assert result.metadata == {"suite": "unit"}


def test_strategy_comparison_rejects_metric_mismatch() -> None:
    session = ResearchSession(
        session_id="session-1",
        name="Metric mismatch",
        entries=(
            ResearchSessionEntry(
                label="baseline",
                strategy_name="momentum",
                manifest=make_manifest(
                    run_id="run-1",
                    objective_metric="other",
                    objective_value=Decimal("1"),
                ),
            ),
        ),
    )

    with pytest.raises(ValueError, match="objective metric"):
        StrategyComparisonEngine(objective_metric="score").compare(session=session)


def test_strategy_comparison_value_objects_validate_inputs() -> None:
    with pytest.raises(ValueError, match="strategy_name"):
        StrategyComparisonResult(
            strategy_name=" ",
            label="baseline",
            run_id="run-1",
            objective_metric="score",
            objective_value=Decimal("1"),
            source_rank=1,
            comparison_rank=1,
            parameters={"lookback": 20},
        )

    result = StrategyComparisonResult(
        strategy_name="momentum",
        label="baseline",
        run_id="run-1",
        objective_metric="score",
        objective_value=Decimal("1"),
        source_rank=1,
        comparison_rank=2,
        parameters={"lookback": 20},
    )
    with pytest.raises(ValueError, match="contiguous rank"):
        StrategyComparisonReport(
            session_id="session-1",
            objective_metric="score",
            results=(result,),
        )


def test_strategy_comparison_rejects_empty_strategy_filter() -> None:
    report = StrategyComparisonEngine(objective_metric="score").compare(
        session=make_session()
    )

    with pytest.raises(ValueError, match="strategy_name"):
        report.results_for_strategy(" ")
