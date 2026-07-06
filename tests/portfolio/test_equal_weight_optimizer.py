from decimal import Decimal

import pytest

from alpha.portfolio import (
    CashReserveConstraint,
    ConstraintSet,
    EqualWeightOptimizer,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_equal_weight_optimizer_allocates_evenly() -> None:
    optimizer = EqualWeightOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT", "GOOGL"),
        )
    )

    assert result.success
    assert result.target_weights == {
        "AAPL": Decimal("0.3333333333333333333333333333"),
        "MSFT": Decimal("0.3333333333333333333333333333"),
        "GOOGL": Decimal("0.3333333333333333333333333333"),
    }
    assert result.cash_weight == Decimal("0")
    assert result.total_weight == Decimal("0.9999999999999999999999999999")
    assert result.metadata["optimizer"] == "equal_weight"


def test_equal_weight_optimizer_respects_cash_reserve() -> None:
    optimizer = EqualWeightOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.20"),
        )
    )

    assert result.success
    assert result.target_weights == {
        "AAPL": Decimal("0.40"),
        "MSFT": Decimal("0.40"),
    }
    assert result.cash_weight == Decimal("0.20")
    assert result.total_weight == Decimal("1.00")


def test_equal_weight_optimizer_calculates_turnover() -> None:
    optimizer = EqualWeightOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={
                "AAPL": Decimal("0.80"),
                "MSFT": Decimal("0.20"),
            },
        )
    )

    assert result.expected_turnover == Decimal("0.30")


def test_equal_weight_optimizer_reports_constraint_violations() -> None:
    optimizer = EqualWeightOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            constraints=ConstraintSet(
                constraints=(PositionLimitConstraint(max_weight=Decimal("0.40")),)
            ),
        )
    )

    assert not result.success
    assert result.has_violations
    assert result.constraint_violations[0].constraint_name == "position_limit"


def test_equal_weight_optimizer_respects_cash_constraint() -> None:
    optimizer = EqualWeightOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.05"),
            constraints=ConstraintSet(
                constraints=(CashReserveConstraint(min_cash_weight=Decimal("0.10")),)
            ),
        )
    )

    assert not result.success
    assert result.constraint_violations[0].constraint_name == "cash_reserve"


def test_equal_weight_optimizer_rejects_cash_reserve_above_one() -> None:
    optimizer = EqualWeightOptimizer()

    with pytest.raises(ValueError):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                cash_reserve=Decimal("1.01"),
            )
        )
