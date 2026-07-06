from decimal import Decimal

import pytest

from alpha.portfolio.allocation.target import AllocationTarget, PortfolioAllocation


def test_allocation_target_creation() -> None:
    target = AllocationTarget(
        symbol="RELIANCE",
        weight=Decimal("0.25"),
    )

    assert target.symbol == "RELIANCE"
    assert target.weight == Decimal("0.25")


def test_allocation_target_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError):
        AllocationTarget(
            symbol="",
            weight=Decimal("0.10"),
        )


def test_allocation_target_rejects_invalid_weight() -> None:
    with pytest.raises(ValueError):
        AllocationTarget(
            symbol="RELIANCE",
            weight=Decimal("1.10"),
        )

    with pytest.raises(ValueError):
        AllocationTarget(
            symbol="RELIANCE",
            weight=Decimal("-1.10"),
        )


def test_portfolio_allocation_creation() -> None:
    allocation = PortfolioAllocation(
        targets=(
            AllocationTarget("RELIANCE", Decimal("0.40")),
            AllocationTarget("TCS", Decimal("0.30")),
            AllocationTarget("INFY", Decimal("0.20")),
        )
    )

    assert allocation.gross_weight == Decimal("0.90")
    assert allocation.net_weight == Decimal("0.90")
    assert allocation.symbols == ("RELIANCE", "TCS", "INFY")
    assert allocation.weight_for("TCS") == Decimal("0.30")
    assert allocation.weight_for("HDFCBANK") == Decimal("0")


def test_portfolio_allocation_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValueError):
        PortfolioAllocation(
            targets=(
                AllocationTarget("RELIANCE", Decimal("0.40")),
                AllocationTarget("RELIANCE", Decimal("0.20")),
            )
        )


def test_portfolio_allocation_rejects_gross_weight_above_one() -> None:
    with pytest.raises(ValueError):
        PortfolioAllocation(
            targets=(
                AllocationTarget("RELIANCE", Decimal("0.60")),
                AllocationTarget("TCS", Decimal("0.50")),
            )
        )


def test_portfolio_allocation_supports_cash_residual() -> None:
    allocation = PortfolioAllocation(
        targets=(
            AllocationTarget("RELIANCE", Decimal("0.25")),
            AllocationTarget("TCS", Decimal("0.25")),
        )
    )

    assert allocation.gross_weight == Decimal("0.50")
    assert allocation.net_weight == Decimal("0.50")
