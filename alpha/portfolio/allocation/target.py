from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    """
    Immutable target allocation for one symbol.
    """

    symbol: str
    weight: Decimal

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("AllocationTarget symbol cannot be empty")

        if self.weight < Decimal("-1"):
            raise ValueError("AllocationTarget weight cannot be less than -1")

        if self.weight > Decimal("1"):
            raise ValueError("AllocationTarget weight cannot be greater than 1")


@dataclass(frozen=True, slots=True)
class PortfolioAllocation:
    """
    Immutable collection of target portfolio weights.
    """

    targets: tuple[AllocationTarget, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()

        for target in self.targets:
            if target.symbol in seen:
                raise ValueError(f"Duplicate allocation target: {target.symbol}")

            seen.add(target.symbol)

        if self.gross_weight > Decimal("1"):
            raise ValueError("PortfolioAllocation gross weight cannot exceed 1")

    @property
    def gross_weight(self) -> Decimal:
        return sum(
            (abs(target.weight) for target in self.targets),
            Decimal("0"),
        )

    @property
    def net_weight(self) -> Decimal:
        return sum(
            (target.weight for target in self.targets),
            Decimal("0"),
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(target.symbol for target in self.targets)

    def weight_for(self, symbol: str) -> Decimal:
        for target in self.targets:
            if target.symbol == symbol:
                return target.weight

        return Decimal("0")
