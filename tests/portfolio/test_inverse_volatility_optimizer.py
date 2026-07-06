from decimal import Decimal

import pytest

from alpha.portfolio import (
    CashReserveConstraint,
    ConstraintSet,
    InverseVolatilityOptimizer,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_inverse_volatility_optimizer_allocates_by_inverse_volatility() -> None:
    optimizer = InverseVolatilityOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
        )
    )

    assert result.success
    assert result.target_weights == {
        "LOW_VOL": Decimal("0.6666666666666666666666666667"),
        "HIGH_VOL": Decimal("0.3333333333333333333333333333"),
    }
    assert result.cash_weight == Decimal("0")
    assert result.metadata["optimizer"] == "inverse_volatility"


def test_inverse_volatility_optimizer_respects_cash_reserve() -> None:
    optimizer = InverseVolatilityOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            cash_reserve=Decimal("0.25"),
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
        )
    )

    assert result.success
    assert result.target_weights == {
        "LOW_VOL": Decimal("0.5000000000000000000000000000"),
        "HIGH_VOL": Decimal("0.2500000000000000000000000000"),
    }
    assert result.cash_weight == Decimal("0.25")
    assert result.total_weight == Decimal("1.000000000000000000000000000")


def test_inverse_volatility_optimizer_calculates_turnover() -> None:
    optimizer = InverseVolatilityOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            current_weights={
                "LOW_VOL": Decimal("0.50"),
                "HIGH_VOL": Decimal("0.50"),
            },
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
        )
    )

    assert result.expected_turnover == Decimal("0.1666666666666666666666666667")


def test_inverse_volatility_optimizer_reports_constraint_violations() -> None:
    optimizer = InverseVolatilityOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
            constraints=ConstraintSet(
                constraints=(PositionLimitConstraint(max_weight=Decimal("0.50")),)
            ),
        )
    )

    assert not result.success
    assert result.has_violations
    assert result.constraint_violations[0].constraint_name == "position_limit"


def test_inverse_volatility_optimizer_respects_cash_constraint() -> None:
    optimizer = InverseVolatilityOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            cash_reserve=Decimal("0.05"),
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
            constraints=ConstraintSet(
                constraints=(CashReserveConstraint(min_cash_weight=Decimal("0.10")),)
            ),
        )
    )

    assert not result.success
    assert result.constraint_violations[0].constraint_name == "cash_reserve"


def test_inverse_volatility_optimizer_rejects_missing_variance() -> None:
    optimizer = InverseVolatilityOptimizer()

    with pytest.raises(ValueError, match="missing variance"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                covariance={},
            )
        )


def test_inverse_volatility_optimizer_rejects_non_positive_variance() -> None:
    optimizer = InverseVolatilityOptimizer()

    with pytest.raises(ValueError, match="must be positive"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                covariance={"AAPL": {"AAPL": Decimal("0")}},
            )
        )


def test_inverse_volatility_optimizer_rejects_cash_reserve_above_one() -> None:
    optimizer = InverseVolatilityOptimizer()

    with pytest.raises(ValueError):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                cash_reserve=Decimal("1.01"),
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
            )
        )
