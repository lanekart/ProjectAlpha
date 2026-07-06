from collections.abc import MutableMapping
from decimal import Decimal
from typing import cast

import pytest

from alpha.portfolio import (
    ConstraintEvaluator,
    ConstraintResult,
    ConstraintSet,
    ConstraintViolation,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_constraint_evaluator_passes_without_constraints() -> None:
    optimization_input = OptimizationInput(universe=("AAPL", "MSFT"))

    result = ConstraintEvaluator().evaluate_input(
        optimization_input=optimization_input,
        target_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
    )

    assert result.passed
    assert not result.failed
    assert result.violations == ()
    assert result.metadata == {"constraint_count": 0}


def test_constraint_evaluator_reports_constraint_violations() -> None:
    optimization_input = OptimizationInput(
        universe=("AAPL", "MSFT"),
        constraints=ConstraintSet(
            constraints=(PositionLimitConstraint(max_weight=Decimal("0.40")),)
        ),
    )

    result = ConstraintEvaluator().evaluate_input(
        optimization_input=optimization_input,
        target_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
    )

    assert not result.passed
    assert result.failed
    assert len(result.violations) == 2
    assert {violation.constraint_name for violation in result.violations} == {
        "position_limit"
    }
    assert result.metadata == {"constraint_count": 1}


def test_constraint_evaluator_can_evaluate_explicit_constraint_set() -> None:
    optimization_input = OptimizationInput(universe=("AAPL", "MSFT"))
    constraints = ConstraintSet(
        constraints=(PositionLimitConstraint(max_weight=Decimal("0.40")),)
    )

    result = ConstraintEvaluator().evaluate(
        constraints=constraints,
        optimization_input=optimization_input,
        target_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
    )

    assert result.failed
    assert result.metadata == {"constraint_count": 1}


def test_constraint_result_is_immutable() -> None:
    result = ConstraintResult(
        violations=(
            ConstraintViolation(
                constraint_name="position_limit",
                message="AAPL weight exceeds position limit",
                actual=Decimal("0.50"),
                limit=Decimal("0.40"),
            ),
        ),
        metadata={"constraint_count": 1},
    )
    metadata = cast(MutableMapping[str, int], result.metadata)

    with pytest.raises(TypeError):
        metadata["constraint_count"] = 2

    assert result.failed
