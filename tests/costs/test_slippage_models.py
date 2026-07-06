from decimal import Decimal

import pytest

from alpha.costs import (
    BasisPointSlippageModel,
    CostInput,
    FixedSlippageModel,
    PerShareSlippageModel,
    TransactionCostEstimator,
)


def test_fixed_slippage_model_returns_fixed_amount() -> None:
    model = FixedSlippageModel(amount=Decimal("15"))

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert cost == Decimal("15")


def test_basis_point_slippage_model_calculates_notional_cost() -> None:
    model = BasisPointSlippageModel(basis_points=Decimal("5"))

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert cost == Decimal("12.5")


def test_per_share_slippage_model_calculates_absolute_quantity_cost() -> None:
    model = PerShareSlippageModel(amount_per_share=Decimal("0.25"))

    buy_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )
    sell_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))
    )

    assert buy_cost == Decimal("2.50")
    assert sell_cost == Decimal("2.50")


def test_slippage_models_reject_negative_values() -> None:
    with pytest.raises(ValueError):
        FixedSlippageModel(amount=Decimal("-1"))

    with pytest.raises(ValueError):
        BasisPointSlippageModel(basis_points=Decimal("-1"))

    with pytest.raises(ValueError):
        PerShareSlippageModel(amount_per_share=Decimal("-1"))


def test_slippage_models_plug_into_transaction_cost_estimator() -> None:
    estimator = TransactionCostEstimator(
        slippage_model=BasisPointSlippageModel(basis_points=Decimal("10"))
    )

    breakdown = estimator.estimate(
        CostInput(symbol="RELIANCE", quantity=20, price=Decimal("2500"))
    )

    assert breakdown.slippage == Decimal("50")
    assert breakdown.total == Decimal("50")
