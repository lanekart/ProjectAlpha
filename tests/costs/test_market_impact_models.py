from decimal import Decimal

import pytest

from alpha.costs import (
    CostInput,
    ParticipationRateImpactModel,
    SquareRootImpactModel,
    TransactionCostEstimator,
)


def test_participation_rate_impact_model_calculates_cost() -> None:
    model = ParticipationRateImpactModel(
        participation_rate=Decimal("0.10"),
        impact_rate=Decimal("0.005"),
    )

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=100, price=Decimal("2500"))
    )

    assert cost == Decimal("125.00000")


def test_participation_rate_impact_model_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        ParticipationRateImpactModel(
            participation_rate=Decimal("-0.01"),
            impact_rate=Decimal("0.005"),
        )

    with pytest.raises(ValueError):
        ParticipationRateImpactModel(
            participation_rate=Decimal("0.10"),
            impact_rate=Decimal("-0.005"),
        )


def test_square_root_impact_model_calculates_cost() -> None:
    model = SquareRootImpactModel(
        daily_volume=Decimal("10000"),
        volatility=Decimal("0.02"),
        impact_coefficient=Decimal("0.5"),
    )

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=100, price=Decimal("2500"))
    )

    assert cost == Decimal("250.000")


def test_square_root_impact_model_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        SquareRootImpactModel(
            daily_volume=Decimal("0"),
            volatility=Decimal("0.02"),
        )

    with pytest.raises(ValueError):
        SquareRootImpactModel(
            daily_volume=Decimal("10000"),
            volatility=Decimal("-0.02"),
        )

    with pytest.raises(ValueError):
        SquareRootImpactModel(
            daily_volume=Decimal("10000"),
            volatility=Decimal("0.02"),
            impact_coefficient=Decimal("-1"),
        )


def test_market_impact_model_plugs_into_transaction_cost_estimator() -> None:
    estimator = TransactionCostEstimator(
        market_impact_model=ParticipationRateImpactModel(
            participation_rate=Decimal("0.10"),
            impact_rate=Decimal("0.005"),
        )
    )

    breakdown = estimator.estimate(
        CostInput(symbol="RELIANCE", quantity=100, price=Decimal("2500"))
    )

    assert breakdown.market_impact == Decimal("125.00000")
    assert breakdown.total == Decimal("125.00000")
