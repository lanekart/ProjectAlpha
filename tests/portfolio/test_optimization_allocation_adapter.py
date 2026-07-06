from decimal import Decimal

import pytest

from alpha.portfolio.allocation import OptimizationAllocationAdapter
from alpha.portfolio.optimization_result import ConstraintViolation, OptimizationResult


def test_adapter_converts_successful_optimization_result_to_allocation() -> None:
    result = OptimizationResult(
        target_weights={
            "RELIANCE": Decimal("0.60"),
            "TCS": Decimal("0.40"),
        },
        success=True,
    )

    allocation = OptimizationAllocationAdapter().to_allocation(result)

    assert allocation.weight_for("RELIANCE") == Decimal("0.60")
    assert allocation.weight_for("TCS") == Decimal("0.40")
    assert allocation.gross_weight == Decimal("1.00")


def test_adapter_sorts_targets_for_deterministic_output() -> None:
    result = OptimizationResult(
        target_weights={
            "TCS": Decimal("0.40"),
            "RELIANCE": Decimal("0.60"),
        },
        success=True,
    )

    allocation = OptimizationAllocationAdapter().to_allocation(result)

    assert allocation.symbols == ("RELIANCE", "TCS")


def test_adapter_excludes_zero_weight_targets_by_default() -> None:
    result = OptimizationResult(
        target_weights={
            "RELIANCE": Decimal("1.00"),
            "TCS": Decimal("0"),
        },
        success=True,
    )

    allocation = OptimizationAllocationAdapter().to_allocation(result)

    assert allocation.symbols == ("RELIANCE",)
    assert allocation.weight_for("TCS") == Decimal("0")


def test_adapter_can_include_zero_weight_targets() -> None:
    result = OptimizationResult(
        target_weights={
            "RELIANCE": Decimal("1.00"),
            "TCS": Decimal("0"),
        },
        success=True,
    )

    allocation = OptimizationAllocationAdapter(
        include_zero_weight_targets=True,
    ).to_allocation(result)

    assert allocation.symbols == ("RELIANCE", "TCS")


def test_adapter_rejects_unsuccessful_optimization_result() -> None:
    result = OptimizationResult(
        target_weights={
            "RELIANCE": Decimal("0.70"),
        },
        success=False,
        constraint_violations=(
            ConstraintViolation(
                constraint_name="position_limit",
                message="Position limit breached",
                actual=Decimal("0.70"),
                limit=Decimal("0.50"),
            ),
        ),
    )

    with pytest.raises(ValueError, match="unsuccessful optimization result"):
        OptimizationAllocationAdapter().to_allocation(result)
