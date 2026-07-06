from decimal import Decimal

import pytest

from alpha.portfolio import (
    BlackLittermanOptimizer,
    BlackLittermanView,
    CashReserveConstraint,
    ConstraintSet,
    OptimizationInput,
    PositionLimitConstraint,
)


def test_black_litterman_optimizer_allocates_by_return_risk_score() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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

    assert result.success
    assert result.target_weights["AAPL"].quantize(Decimal("0.000001")) == Decimal(
        "0.666667"
    )
    assert result.target_weights["MSFT"].quantize(Decimal("0.000001")) == Decimal(
        "0.333333"
    )
    assert result.metadata["optimizer"] == "black_litterman"


def test_black_litterman_optimizer_blends_views() -> None:
    optimizer = BlackLittermanOptimizer(
        views=(
            BlackLittermanView(
                symbol="MSFT",
                expected_return=Decimal("0.24"),
                confidence=Decimal("1"),
            ),
        )
    )

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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

    assert result.success
    assert result.target_weights["MSFT"] > result.target_weights["AAPL"]
    assert result.metadata["views"] == "1"


def test_black_litterman_optimizer_respects_cash_reserve() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.20"),
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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

    assert result.success
    assert result.cash_weight == Decimal("0.20")
    assert result.total_weight.quantize(Decimal("0.000001")) == Decimal("1.000000")


def test_black_litterman_optimizer_calculates_turnover() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={
                "AAPL": Decimal("0.50"),
                "MSFT": Decimal("0.50"),
            },
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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

    assert result.expected_turnover.quantize(Decimal("0.000001")) == Decimal("0.166667")


def test_black_litterman_optimizer_reports_constraint_violations() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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
            constraints=ConstraintSet(
                constraints=(PositionLimitConstraint(max_weight=Decimal("0.50")),)
            ),
        )
    )

    assert not result.success
    assert result.has_violations
    assert result.constraint_violations[0].constraint_name == "position_limit"


def test_black_litterman_optimizer_respects_cash_constraint() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            cash_reserve=Decimal("0.05"),
            expected_returns={
                "AAPL": Decimal("0.12"),
                "MSFT": Decimal("0.06"),
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
            constraints=ConstraintSet(
                constraints=(CashReserveConstraint(min_cash_weight=Decimal("0.10")),)
            ),
        )
    )

    assert not result.success
    assert result.constraint_violations[0].constraint_name == "cash_reserve"


def test_black_litterman_optimizer_uses_equal_weight_for_negative_returns() -> None:
    optimizer = BlackLittermanOptimizer()

    result = optimizer.optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            expected_returns={
                "AAPL": Decimal("-0.01"),
                "MSFT": Decimal("-0.02"),
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

    assert result.success
    assert result.target_weights["AAPL"] == Decimal("0.5")
    assert result.target_weights["MSFT"] == Decimal("0.5")


def test_black_litterman_optimizer_rejects_missing_expected_return() -> None:
    optimizer = BlackLittermanOptimizer()

    with pytest.raises(ValueError, match="missing expected return"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                expected_returns={},
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
            )
        )


def test_black_litterman_optimizer_rejects_missing_covariance_row() -> None:
    optimizer = BlackLittermanOptimizer()

    with pytest.raises(ValueError, match="missing covariance row"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                expected_returns={"AAPL": Decimal("0.10")},
                covariance={},
            )
        )


def test_black_litterman_optimizer_rejects_missing_covariance_value() -> None:
    optimizer = BlackLittermanOptimizer()

    with pytest.raises(ValueError, match="missing covariance value"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL", "MSFT"),
                expected_returns={
                    "AAPL": Decimal("0.10"),
                    "MSFT": Decimal("0.08"),
                },
                covariance={
                    "AAPL": {"AAPL": Decimal("0.04")},
                    "MSFT": {
                        "AAPL": Decimal("0"),
                        "MSFT": Decimal("0.04"),
                    },
                },
            )
        )


def test_black_litterman_optimizer_rejects_non_positive_variance() -> None:
    optimizer = BlackLittermanOptimizer()

    with pytest.raises(ValueError, match="must be positive"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                expected_returns={"AAPL": Decimal("0.10")},
                covariance={"AAPL": {"AAPL": Decimal("0")}},
            )
        )


def test_black_litterman_optimizer_rejects_view_outside_universe() -> None:
    optimizer = BlackLittermanOptimizer(
        views=(
            BlackLittermanView(
                symbol="TSLA",
                expected_return=Decimal("0.20"),
                confidence=Decimal("0.80"),
            ),
        )
    )

    with pytest.raises(ValueError, match="not in universe"):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                expected_returns={"AAPL": Decimal("0.10")},
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
            )
        )


def test_black_litterman_view_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        BlackLittermanView(
            symbol="AAPL",
            expected_return=Decimal("0.10"),
            confidence=Decimal("0"),
        )

    with pytest.raises(ValueError):
        BlackLittermanView(
            symbol="AAPL",
            expected_return=Decimal("0.10"),
            confidence=Decimal("1.01"),
        )


def test_black_litterman_optimizer_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        BlackLittermanOptimizer(risk_aversion=Decimal("0"))

    with pytest.raises(ValueError):
        BlackLittermanOptimizer(tau=Decimal("0"))


def test_black_litterman_optimizer_rejects_cash_reserve_above_one() -> None:
    optimizer = BlackLittermanOptimizer()

    with pytest.raises(ValueError):
        optimizer.optimize(
            OptimizationInput(
                universe=("AAPL",),
                cash_reserve=Decimal("1.01"),
                expected_returns={"AAPL": Decimal("0.10")},
                covariance={"AAPL": {"AAPL": Decimal("0.04")}},
            )
        )
