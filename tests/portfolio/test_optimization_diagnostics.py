from decimal import Decimal

import pytest

from alpha.portfolio import (
    ConstraintSet,
    EqualWeightOptimizer,
    OptimizationDiagnostics,
    OptimizationInput,
    PositionLimitConstraint,
)
from alpha.portfolio.optimization_diagnostics import OptimizationDiagnostics as DirectDiagnostics
from alpha.portfolio.optimization_result import OptimizationResult


def test_optimization_diagnostics_from_successful_result() -> None:
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        current_weights={"AAPL": Decimal("1"), "MSFT": Decimal("0")},
    )
    result = EqualWeightOptimizer().optimize(optimization_input)

    diagnostics = OptimizationDiagnostics.from_optimization(
        optimization_input=optimization_input,
        result=result,
    )

    assert diagnostics.optimizer == "equal_weight"
    assert diagnostics.universe_size == 2
    assert diagnostics.invested_weight == Decimal("1.0")
    assert diagnostics.cash_weight == Decimal("0")
    assert diagnostics.total_weight == Decimal("1.0")
    assert diagnostics.expected_turnover == Decimal("0.5")
    assert diagnostics.objective_scores == {"turnover": Decimal("0.5")}
    assert not diagnostics.has_violations


def test_optimization_diagnostics_groups_constraint_violations() -> None:
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        constraints=ConstraintSet(
            constraints=(PositionLimitConstraint(max_weight=Decimal("0.40")),)
        ),
    )
    result = EqualWeightOptimizer().optimize(optimization_input)

    diagnostics = OptimizationDiagnostics.from_optimization(
        optimization_input=optimization_input,
        result=result,
    )

    assert diagnostics.has_violations
    assert tuple(diagnostics.violations_by_constraint) == ("position_limit",)
    assert len(diagnostics.violations_by_constraint["position_limit"]) == 2


def test_optimization_diagnostics_is_immutable() -> None:
    diagnostics = DirectDiagnostics(
        optimizer=" equal_weight ",
        universe_size=2,
        invested_weight=Decimal("1"),
        cash_weight=Decimal("0"),
        total_weight=Decimal("1"),
        expected_turnover=Decimal("0"),
        objective_scores={"turnover": Decimal("0")},
    )

    assert diagnostics.optimizer == "equal_weight"

    with pytest.raises(TypeError):
        diagnostics.objective_scores["turnover"] = Decimal("1")  # type: ignore[index]


def test_optimization_diagnostics_falls_back_for_missing_metadata() -> None:
    optimization_input = OptimizationInput(universe=("AAPL",))
    result = OptimizationResult(target_weights={"AAPL": Decimal("1")}, success=True)

    diagnostics = OptimizationDiagnostics.from_optimization(
        optimization_input=optimization_input,
        result=result,
    )

    assert diagnostics.optimizer == "unknown"
    assert diagnostics.objective_scores == {}


def test_optimization_diagnostics_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        DirectDiagnostics(
            optimizer="",
            universe_size=1,
            invested_weight=Decimal("1"),
            cash_weight=Decimal("0"),
            total_weight=Decimal("1"),
            expected_turnover=Decimal("0"),
        )
