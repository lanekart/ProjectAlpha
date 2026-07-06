"""Portfolio optimizer interfaces and shared input objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol

from alpha.portfolio.constraints import ConstraintSet
from alpha.portfolio.optimization_result import OptimizationResult


@dataclass(frozen=True, slots=True)
class OptimizationInput:
    """Immutable optimizer input independent from execution/accounting."""

    universe: tuple[str, ...]
    current_weights: Mapping[str, Decimal] = field(default_factory=dict)
    expected_returns: Mapping[str, Decimal] = field(default_factory=dict)
    covariance: Mapping[str, Mapping[str, Decimal]] = field(default_factory=dict)
    sector_by_symbol: Mapping[str, str] = field(default_factory=dict)
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    cash_reserve: Decimal = Decimal("0")
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.universe) == 0:
            raise ValueError("universe cannot be empty")

        if len(set(self.universe)) != len(self.universe):
            raise ValueError("universe cannot contain duplicate symbols")

        if self.cash_reserve < Decimal("0"):
            raise ValueError("cash_reserve cannot be negative")

        object.__setattr__(
            self,
            "current_weights",
            MappingProxyType(dict(self.current_weights)),
        )
        object.__setattr__(
            self,
            "expected_returns",
            MappingProxyType(dict(self.expected_returns)),
        )
        object.__setattr__(
            self,
            "sector_by_symbol",
            MappingProxyType(dict(self.sector_by_symbol)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

        copied_covariance = {
            symbol: MappingProxyType(dict(row))
            for symbol, row in self.covariance.items()
        }
        object.__setattr__(
            self,
            "covariance",
            MappingProxyType(copied_covariance),
        )


class Optimizer(Protocol):
    """Protocol for all portfolio optimizers."""

    @property
    def name(self) -> str:
        """Return optimizer name."""

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Optimize portfolio target weights."""
