from decimal import Decimal

import pytest

from alpha.portfolio import (
    CashReserveConstraint,
    ConstraintSet,
    MinimumVarianceOptimizer,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_minimum_variance_optimizer_allocates_equal_for_equal_risk_assets() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            covariance={
                "AAPL": {
                    "AAPL": Decimal("0.04"),
                    "MSFT": Decimal("0"),
                },
                "MSFT": {
                    "AAPL": Decimal("0"),
                    "MSFT": Decimal("0.04"),
                },
            },
        )
    )

    assert result.success
    assert result.target_weights["AAPL"].quantize(Decimal("0.000001")) == Decimal(
        "0.500000"
    )
    assert result.target_weights["MSFT"].quantize(Decimal("0.000001")) == Decimal(
        "0.500000"
    )
    assert result.metadata["optimizer"] == "minimum_variance"


def test_minimum_variance_optimizer_allocates_more_to_lower_variance_asset() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VAR", "HIGH_VAR"),
            covariance={
                "LOW_VAR": {
                    "LOW_VAR": Decimal("0.04"),
                    "HIGH_VAR": Decimal("0"),
                },
                "HIGH_VAR": {
                    "LOW_VAR": Decimal("0"),
                    "HIGH_VAR": Decimal("0.16"),
                },
            },
        )
    )

    assert result.success
    assert result.target_weights["LOW_VAR"] > result.target_weights["HIGH_VAR"]


def test_minimum_variance_optimizer_respects_cash_reserve() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.20"),
            covariance={
                "AAPL": {
                    "AAPL": Decimal("0.04"),
                    "MSFT": Decimal("0"),
                },
                "MSFT": {
                    "AAPL": Decimal("0"),
                    "MSFT": Decimal("0.04"),
                },
            },
        )
    )

    assert result.success
    assert result.cash_weight == Decimal("0.20")
    assert result.total_weight.quantize(Decimal("0.000001")) == Decimal("1.000000")


def test_minimum_variance_optimizer_calculates_turnover() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={
                "AAPL": Decimal("0.80"),
                "MSFT": Decimal("0.20"),
            },
            covariance={
                "AAPL": {
                    "AAPL": Decimal("0.04"),
                    "MSFT": Decimal("0"),
                },
                "MSFT": {
                    "AAPL": Decimal("0"),
                    "MSFT": Decimal("0.04"),
                },
            },
        )
    )

    assert result.expected_turnover.quantize(Decimal("0.000001")) == Decimal("0.300000")


def test_minimum_variance_optimizer_reports_constraint_violations() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VAR", "HIGH_VAR"),
            covariance={
                "LOW_VAR": {
                    "LOW_VAR": Decimal("0.04"),
                    "HIGH_VAR": Decimal("0"),
                },
                "HIGH_VAR": {
                    "LOW_VAR": Decimal("0"),
                    "HIGH_VAR": Decimal("0.16"),
                },
            },
            constraints=ConstraintSet(
                constraints=(PositionLimitConstraint(max_weight=Decimal("0.50")),)
            ),
        )
    )

    assert not result.success
    assert result.has_violations
    assert result.constraint_violations[0].constraint_name == "position_limit"


def test_minimum_variance_optimizer_respects_cash_constraint() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.05"),
            covariance={
                "AAPL": {
                    "AAPL": Decimal("0.04"),
                    "MSFT": Decimal("0"),
                },
                "MSFT": {
                    "AAPL": Decimal("0"),
                    "MSFT": Decimal("0.04"),
                },
            },
            constraints=ConstraintSet(
                constraints=(CashReserveConstraint(min_cash_weight=Decimal("0.10")),)
            ),
        )
    )

    assert not result.success
    assert result.constraint_violations[0].constraint_name == "cash_reserve"


def test_minimum_variance_optimizer_handles_single_asset() -> None:
    optimizer = MinimumVarianceOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL",),
            covariance={"AAPL": {"AAPL": Decimal("0.04")}},
        )
    )

    assert result.success
    assert result.target_weights == {"AAPL": Decimal("1")}


def test_minimum_variance_optimizer_rejects_missing_covariance_row() -> None:
    optimizer = MinimumVarianceOptimizer()

    with pytest.raises(ValueError, match="missing covariance row"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                covariance={},
            )
        )


def test_minimum_variance_optimizer_rejects_missing_covariance_value() -> None:
    optimizer = MinimumVarianceOptimizer()

    with pytest.raises(ValueError, match="missing covariance value"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                covariance={
                    "AAPL": {"AAPL": Decimal("0.04")},
                    "MSFT": {
                        "AAPL": Decimal("0"),
                        "MSFT": Decimal("0.04"),
                    },
                },
            )
        )


def test_minimum_variance_optimizer_rejects_non_positive_variance() -> None:
    optimizer = MinimumVarianceOptimizer()

    with pytest.raises(ValueError, match="must be positive"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                covariance={"AAPL": {"AAPL": Decimal("0")}},
            )
        )


def test_minimum_variance_optimizer_rejects_singular_covariance() -> None:
    optimizer = MinimumVarianceOptimizer()

    with pytest.raises(ValueError, match="singular"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                covariance={
                    "AAPL": {
                        "AAPL": Decimal("0.04"),
                        "MSFT": Decimal("0.04"),
                    },
                    "MSFT": {
                        "AAPL": Decimal("0.04"),
                        "MSFT": Decimal("0.04"),
                    },
                },
            )
        )


def test_minimum_variance_optimizer_rejects_cash_reserve_above_one() -> None:
    optimizer = MinimumVarianceOptimizer()

    with pytest.raises(ValueError):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                cash_reserve=Decimal("1.01"),
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
            )
        )
