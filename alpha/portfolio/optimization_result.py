"""Immutable optimization result value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    """Represents a single optimization constraint violation."""

    constraint_name: str
    message: str
    actual: Decimal | None = None
    limit: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Immutable output produced by a portfolio optimizer."""

    target_weights: Mapping[str, Decimal]
    success: bool
    expected_turnover: Decimal = Decimal("0")
    cash_weight: Decimal = Decimal("0")
    constraint_violations: tuple[ConstraintViolation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_weights",
            MappingProxyType(dict(self.target_weights)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

        if self.expected_turnover < Decimal("0"):
            raise ValueError("expected_turnover cannot be negative")

        if self.cash_weight < Decimal("0"):
            raise ValueError("cash_weight cannot be negative")

        for symbol, weight in self.target_weights.items():
            if not symbol:
                raise ValueError("target weight symbol cannot be empty")
            if weight < Decimal("0"):
                raise ValueError(f"target weight for {symbol} cannot be negative")

    @property
    def invested_weight(self) -> Decimal:
        """Return total non-cash portfolio weight."""

        return sum(self.target_weights.values(), Decimal("0"))

    @property
    def total_weight(self) -> Decimal:
        """Return invested plus cash weight."""

        return self.invested_weight + self.cash_weight

    @property
    def has_violations(self) -> bool:
        """Return whether the optimization result violated constraints."""

        return len(self.constraint_violations) > 0
