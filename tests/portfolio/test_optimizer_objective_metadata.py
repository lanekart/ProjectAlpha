from decimal import Decimal

from alpha.portfolio import (
    BlackLittermanOptimizer,
    EqualWeightOptimizer,
    InverseVolatilityOptimizer,
    MinimumVarianceOptimizer,
    OptimizationInput,
    RiskParityOptimizer,
)


def test_equal_weight_optimizer_reports_turnover_objective_metadata() -> None:
    result = EqualWeightOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={"AAPL": Decimal("0.80"), "MSFT": Decimal("0.20")},
        )
    )

    assert result.metadata["objectives"] == {"turnover": Decimal("0.30")}


def test_inverse_volatility_optimizer_reports_turnover_objective_metadata() -> None:
    result = InverseVolatilityOptimizer().optimize(
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

    objectives = result.metadata["objectives"]

    assert objectives == {"turnover": result.expected_turnover}
    assert "variance" not in objectives


def test_minimum_variance_optimizer_reports_turnover_and_variance_metadata() -> None:
    result = MinimumVarianceOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.16")},
            },
        )
    )

    objectives = result.metadata["objectives"]

    assert objectives["turnover"] == result.expected_turnover
    assert objectives["variance"] > Decimal("0")


def test_risk_parity_optimizer_reports_turnover_and_variance_metadata() -> None:
    result = RiskParityOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.16")},
            },
        )
    )

    objectives = result.metadata["objectives"]

    assert objectives["turnover"] == result.expected_turnover
    assert objectives["variance"] > Decimal("0")


def test_black_litterman_optimizer_reports_objective_metadata() -> None:
    result = BlackLittermanOptimizer().optimize(
        OptimizationInput(
            universe=("AAPL", "MSFT"),
            current_weights={"AAPL": Decimal("0.50"), "MSFT": Decimal("0.50")},
            expected_returns={"AAPL": Decimal("0.12"), "MSFT": Decimal("0.06")},
            covariance={
                "AAPL": {"AAPL": Decimal("0.04"), "MSFT": Decimal("0")},
                "MSFT": {"AAPL": Decimal("0"), "MSFT": Decimal("0.04")},
            },
        )
    )

    objectives = result.metadata["objectives"]

    assert objectives["expected_return"] > Decimal("0")
    assert objectives["turnover"] == result.expected_turnover
    assert objectives["variance"] > Decimal("0")
