from decimal import Decimal

import pytest

from alpha.costs import (
    CostBreakdown,
    CostInput,
    FixedCommissionModel,
    PercentageCommissionModel,
    TransactionCostEstimator,
)


def test_cost_input_calculates_absolute_notional() -> None:
    buy = CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    sell = CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))

    assert buy.notional == Decimal("25000")
    assert sell.notional == Decimal("25000")


def test_cost_input_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        CostInput(symbol="", quantity=10, price=Decimal("2500"))

    with pytest.raises(ValueError):
        CostInput(symbol="RELIANCE", quantity=0, price=Decimal("2500"))

    with pytest.raises(ValueError):
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("0"))


def test_cost_breakdown_calculates_total() -> None:
    breakdown = CostBreakdown(
        commission=Decimal("10"),
        slippage=Decimal("5"),
        market_impact=Decimal("3"),
        taxes=Decimal("2"),
        fees=Decimal("1"),
    )

    assert breakdown.total == Decimal("21")


def test_cost_breakdown_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        CostBreakdown(commission=Decimal("-1"))


def test_fixed_commission_model() -> None:
    model = FixedCommissionModel(amount=Decimal("20"))

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert cost == Decimal("20")


def test_percentage_commission_model() -> None:
    model = PercentageCommissionModel(rate=Decimal("0.001"))

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert cost == Decimal("25.000")


def test_transaction_cost_estimator_returns_zero_without_models() -> None:
    estimator = TransactionCostEstimator()

    breakdown = estimator.estimate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert breakdown.total == Decimal("0")


def test_transaction_cost_estimator_combines_models() -> None:
    estimator = TransactionCostEstimator(
        commission_model=FixedCommissionModel(amount=Decimal("20")),
        fee_model=PercentageCommissionModel(rate=Decimal("0.001")),
    )

    breakdown = estimator.estimate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert breakdown.commission == Decimal("20")
    assert breakdown.fees == Decimal("25.000")
    assert breakdown.total == Decimal("45.000")
