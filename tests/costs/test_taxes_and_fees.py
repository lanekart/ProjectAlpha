from decimal import Decimal

import pytest

from alpha.costs import (
    CappedPercentageFeeModel,
    CostInput,
    FlatFeeModel,
    PercentageTaxModel,
    TransactionCostEstimator,
)


def test_percentage_tax_model_applies_to_buys_and_sells_by_default() -> None:
    model = PercentageTaxModel(rate=Decimal("0.001"))

    buy_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )
    sell_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))
    )

    assert buy_cost == Decimal("25.000")
    assert sell_cost == Decimal("25.000")


def test_percentage_tax_model_can_apply_only_to_sells() -> None:
    model = PercentageTaxModel(
        rate=Decimal("0.001"),
        applies_to_buys=False,
        applies_to_sells=True,
    )

    buy_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )
    sell_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))
    )

    assert buy_cost == Decimal("0")
    assert sell_cost == Decimal("25.000")


def test_percentage_tax_model_can_apply_only_to_buys() -> None:
    model = PercentageTaxModel(
        rate=Decimal("0.001"),
        applies_to_buys=True,
        applies_to_sells=False,
    )

    buy_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )
    sell_cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))
    )

    assert buy_cost == Decimal("25.000")
    assert sell_cost == Decimal("0")


def test_percentage_tax_model_rejects_invalid_config() -> None:
    with pytest.raises(ValueError):
        PercentageTaxModel(rate=Decimal("-0.001"))

    with pytest.raises(ValueError):
        PercentageTaxModel(
            rate=Decimal("0.001"),
            applies_to_buys=False,
            applies_to_sells=False,
        )


def test_flat_fee_model_returns_fixed_amount() -> None:
    model = FlatFeeModel(amount=Decimal("10"))

    cost = model.calculate(
        CostInput(symbol="RELIANCE", quantity=10, price=Decimal("2500"))
    )

    assert cost == Decimal("10")


def test_capped_percentage_fee_model_applies_cap() -> None:
    model = CappedPercentageFeeModel(
        rate=Decimal("0.01"),
        cap=Decimal("100"),
    )

    uncapped = model.calculate(
        CostInput(symbol="RELIANCE", quantity=1, price=Decimal("2500"))
    )
    capped = model.calculate(
        CostInput(symbol="RELIANCE", quantity=100, price=Decimal("2500"))
    )

    assert uncapped == Decimal("25.00")
    assert capped == Decimal("100")


def test_fee_models_reject_negative_values() -> None:
    with pytest.raises(ValueError):
        FlatFeeModel(amount=Decimal("-1"))

    with pytest.raises(ValueError):
        CappedPercentageFeeModel(
            rate=Decimal("-0.01"),
            cap=Decimal("100"),
        )

    with pytest.raises(ValueError):
        CappedPercentageFeeModel(
            rate=Decimal("0.01"),
            cap=Decimal("-100"),
        )


def test_tax_and_fee_models_plug_into_transaction_cost_estimator() -> None:
    estimator = TransactionCostEstimator(
        tax_model=PercentageTaxModel(
            rate=Decimal("0.001"),
            applies_to_buys=False,
            applies_to_sells=True,
        ),
        fee_model=CappedPercentageFeeModel(
            rate=Decimal("0.001"),
            cap=Decimal("20"),
        ),
    )

    breakdown = estimator.estimate(
        CostInput(symbol="RELIANCE", quantity=-10, price=Decimal("2500"))
    )

    assert breakdown.taxes == Decimal("25.000")
    assert breakdown.fees == Decimal("20")
    assert breakdown.total == Decimal("45.000")
