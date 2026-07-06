from decimal import Decimal

import pytest

from alpha.costs import FixedCommissionModel, TransactionCostEstimator
from alpha.optimization import (
    ConcentrationObjective,
    ExpectedReturnObjective,
    ObjectiveEvaluator,
    ObjectiveResult,
    TrackingErrorObjective,
    TransactionCostObjective,
    TurnoverObjective,
    VarianceObjective,
    WeightedObjective,
    WeightedObjectiveComponent,
)
from alpha.portfolio import OptimizationInput


def test_objective_result_is_immutable() -> None:
    result = ObjectiveResult(
        name="test",
        score=Decimal("1"),
        components={"alpha": Decimal("0.5")},
        metadata={"source": "unit"},
    )

    with pytest.raises(TypeError):
        result.components["alpha"] = Decimal("1")  # type: ignore[index]

    with pytest.raises(TypeError):
        result.metadata["source"] = "changed"  # type: ignore[index]


def test_objective_result_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        ObjectiveResult(name=" ", score=Decimal("0"))


def test_expected_return_objective_scores_weighted_return() -> None:
    objective = ExpectedReturnObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        expected_returns={
            "AAPL": Decimal("0.10"),
            "MSFT": Decimal("0.20"),
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.25"),
            "MSFT": Decimal("0.75"),
        },
    )

    assert result.name == "expected_return"
    assert result.score == Decimal("0.1750")


def test_variance_objective_scores_portfolio_variance() -> None:
    objective = VarianceObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        covariance={
            "AAPL": {
                "AAPL": Decimal("0.04"),
                "MSFT": Decimal("0.01"),
            },
            "MSFT": {
                "AAPL": Decimal("0.01"),
                "MSFT": Decimal("0.09"),
            },
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.50"),
            "MSFT": Decimal("0.50"),
        },
    )

    assert result.name == "variance"
    assert result.score == Decimal("0.0375")


def test_variance_objective_rejects_missing_covariance() -> None:
    objective = VarianceObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        covariance={
            "AAPL": {
                "AAPL": Decimal("0.04"),
            },
        },
    )

    with pytest.raises(ValueError):
        objective.evaluate(
            optimization_input=optimization_input,
            target_weights={
                "AAPL": Decimal("0.50"),
                "MSFT": Decimal("0.50"),
            },
        )


def test_turnover_objective_scores_half_absolute_weight_change() -> None:
    objective = TurnoverObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        current_weights={
            "AAPL": Decimal("0.70"),
            "MSFT": Decimal("0.30"),
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.50"),
            "MSFT": Decimal("0.50"),
        },
    )

    assert result.name == "turnover"
    assert result.score == Decimal("0.20")


def test_concentration_objective_scores_hhi() -> None:
    objective = ConcentrationObjective()
    optimization_input = OptimizationInput(universe=("AAPL", "MSFT"))

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.60"),
            "MSFT": Decimal("0.40"),
        },
    )

    assert result.name == "concentration"
    assert result.score == Decimal("0.52")


def test_transaction_cost_objective_scores_cost_weight() -> None:
    objective = TransactionCostObjective(
        cost_estimator=TransactionCostEstimator(
            commission_model=FixedCommissionModel(amount=Decimal("20"))
        )
    )
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        current_weights={
            "AAPL": Decimal("0.50"),
            "MSFT": Decimal("0.50"),
        },
        metadata={
            "portfolio_value": Decimal("100000"),
            "prices": {
                "AAPL": Decimal("100"),
                "MSFT": Decimal("200"),
            },
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.60"),
            "MSFT": Decimal("0.40"),
        },
    )

    assert result.name == "transaction_cost"
    assert result.components["transaction_cost"] == Decimal("40")
    assert result.score == Decimal("0.0004")


def test_tracking_error_objective_scores_active_variance() -> None:
    objective = TrackingErrorObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        covariance={
            "AAPL": {
                "AAPL": Decimal("0.04"),
                "MSFT": Decimal("0.01"),
            },
            "MSFT": {
                "AAPL": Decimal("0.01"),
                "MSFT": Decimal("0.09"),
            },
        },
        metadata={
            "benchmark_weights": {
                "AAPL": Decimal("0.50"),
                "MSFT": Decimal("0.50"),
            },
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.60"),
            "MSFT": Decimal("0.40"),
        },
    )

    assert result.name == "tracking_error"
    assert result.score == Decimal("0.0011")


def test_weighted_objective_combines_component_scores() -> None:
    objective = WeightedObjective(
        components=(
            WeightedObjectiveComponent(
                objective=ExpectedReturnObjective(),
                weight=Decimal("1"),
            ),
            WeightedObjectiveComponent(
                objective=ConcentrationObjective(),
                weight=Decimal("-0.5"),
            ),
        )
    )
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        expected_returns={
            "AAPL": Decimal("0.10"),
            "MSFT": Decimal("0.20"),
        },
    )

    result = objective.evaluate(
        optimization_input=optimization_input,
        target_weights={
            "AAPL": Decimal("0.50"),
            "MSFT": Decimal("0.50"),
        },
    )

    assert result.name == "weighted_objective"
    assert result.score == Decimal("-0.10")
    assert result.components["expected_return"] == Decimal("0.1500")
    assert result.components["concentration"] == Decimal("0.50")


def test_weighted_objective_rejects_empty_components() -> None:
    with pytest.raises(ValueError):
        WeightedObjective(components=())


def test_weighted_objective_component_rejects_zero_weight() -> None:
    with pytest.raises(ValueError):
        WeightedObjectiveComponent(
            objective=ExpectedReturnObjective(),
            weight=Decimal("0"),
        )


def test_objective_evaluator_evaluates_and_scores_objectives() -> None:
    evaluator = ObjectiveEvaluator()
    objective = ExpectedReturnObjective()
    optimization_input = OptimizationInput(
        universe=("AAPL",),
        expected_returns={"AAPL": Decimal("0.12")},
    )
    target_weights = {"AAPL": Decimal("1")}

    result = evaluator.evaluate(
        objective=objective,
        optimization_input=optimization_input,
        target_weights=target_weights,
    )

    assert result.score == Decimal("0.12")
    assert evaluator.score(
        objective=objective,
        optimization_input=optimization_input,
        target_weights=target_weights,
    ) == Decimal("0.12")
