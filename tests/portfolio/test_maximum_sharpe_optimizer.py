from decimal import Decimal

import pytest

from alpha.portfolio import (
    ConstraintSet,
    MaximumSharpeOptimizer,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_maximum_sharpe_optimizer_prefers_best_risk_adjusted_return() -> None:
    result = MaximumSharpeOptimizer().optimize(
        OptimizationInput(
            universe=("HIGH", "LOW"),
            expected_returns={"HIGH": Decimal("0.12"), "LOW": Decimal("0.06")},
            covariance={
                "HIGH": {"HIGH": Decimal("0.04")},
                "LOW": {"LOW": Decimal("0.04")},
            },
        )
    )

    assert result.success
    assert result.target_weights["HIGH"] == Decimal("0.6666666666666666666666666667")
    assert result.target_weights["LOW"] == Decimal("0.3333333333333333333333333333")
    assert result.metadata["optimizer"] == "maximum_sharpe"


def test_maximum_sharpe_optimizer_penalizes_higher_volatility() -> None:
    result = MaximumSharpeOptimizer().optimize(
        OptimizationInput(
            universe=("LOW_VOL", "HIGH_VOL"),
            expected_returns={
                "LOW_VOL": Decimal("0.10"),
                "HIGH_VOL": Decimal("0.10"),
            },
            covariance={
                "LOW_VOL": {"LOW_VOL": Decimal("0.04")},
                "HIGH_VOL": {"HIGH_VOL": Decimal("0.16")},
            },
        )
    )

    assert result.target_weights["LOW_VOL"] == Decimal("0.6666666666666666666666666667")
    assert result.target_weights["HIGH_VOL"] == Decimal("0.3333333333333333333333333333")


def test_maximum_sharpe_optimizer_respects_cash_reserve() -> None:
    result = MaximumSharpeOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={"AAPL": Decimal("0.12"), "MSFT": Decimal("0.06")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04")},
                "MSFT": {"MSFT": Decimal("0.04")},
            },
            cash_reserve=Decimal("0.10"),
        )
    )

    assert result.cash_weight == Decimal("0.10")
    assert result.invested_weight == Decimal("0.9000000000000000000000000000")
    assert result.total_weight == Decimal("1.000000000000000000000000000")


def test_maximum_sharpe_optimizer_falls_back_to_equal_weight_when_no_positive_scores() -> None:
    result = MaximumSharpeOptimizer(risk_free_rate=Decimal("0.05")).optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={"AAPL": Decimal("0.02"), "MSFT": Decimal("0.03")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04")},
                "MSFT": {"MSFT": Decimal("0.09")},
            },
        )
    )

    assert result.target_weights == {"AAPL": Decimal("0.5"), "MSFT": Decimal("0.5")}


def test_maximum_sharpe_optimizer_reports_objective_metadata() -> None:
    result = MaximumSharpeOptimizer(risk_free_rate=Decimal("0.02")).optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={"AAPL": Decimal("1"), "MSFT": Decimal("0")},
            expected_returns={"AAPL": Decimal("0.12"), "MSFT": Decimal("0.06")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.04")},
            },
        )
    )

    objectives = result.metadata["objectives"]

    assert result.metadata["risk_free_rate"] == Decimal("0.02")
    assert objectives["expected_return"] > Decimal("0")
    assert objectives["turnover"] == result.expected_turnover
    assert objectives["variance"] > Decimal("0")


def test_maximum_sharpe_optimizer_reports_constraint_violations() -> None:
    result = MaximumSharpeOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={"AAPL": Decimal("0.12"), "MSFT": Decimal("0.06")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04")},
                "MSFT": {"MSFT": Decimal("0.04")},
            },
            constraints=ConstraintSet(
                constraints=(PositionLimitConstraint(max_weight=Decimal("0.60")),)
            ),
        )
    )

    assert not result.success
    assert result.has_violations
    assert result.constraint_violations[0].constraint_name == "position_limit"


def test_maximum_sharpe_optimizer_rejects_missing_expected_return() -> None:
    with pytest.raises(ValueError, match="missing expected return for MSFT"):
        MaximumSharpeOptimizer().optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                expected_returns={"AAPL": Decimal("0.12")},
                covariance={
                    "AAPL": {"AAPL": Decimal("0.04")},
                    "MSFT": {"MSFT": Decimal("0.04")},
                },
            )
        )


def test_maximum_sharpe_optimizer_rejects_missing_variance() -> None:
    with pytest.raises(ValueError, match="missing variance for MSFT"):
        MaximumSharpeOptimizer().optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                expected_returns={"AAPL": Decimal("0.12"), "MSFT": Decimal("0.06")},
                covariance={
                    "AAPL": {"AAPL": Decimal("0.04")},
                    "MSFT": {},
                },
            )
        )


def test_maximum_sharpe_optimizer_rejects_cash_reserve_above_one() -> None:
    with pytest.raises(ValueError, match="cash_reserve cannot exceed 1"):
        MaximumSharpeOptimizer().optimize(
            OptimizationInput(
                universe=("AAPL",),
                expected_returns={"AAPL": Decimal("0.12")},
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
                cash_reserve=Decimal("1.01"),
            )
        )
