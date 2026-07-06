"""Portfolio optimization constraint framework."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from alpha.portfolio.optimization_result import ConstraintViolation


class PortfolioConstraint(Protocol):
    """Protocol implemented by all optimizer constraints."""

    @property
    def name(self) -> str:
        """Return the constraint name."""

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        """Validate target weights against this constraint."""


@dataclass(frozen=True, slots=True)
class PositionLimitConstraint:
    """Maximum weight allowed in a single position."""

    max_weight: Decimal
    name: str = "position_limit"

    def __post_init__(self) -> None:
        if self.max_weight <= Decimal("0"):
            raise ValueError("max_weight must be positive")

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        del current_weights, sector_by_symbol, cash_weight

        violations: list[ConstraintViolation] = []
        for symbol, weight in target_weights.items():
            if weight > self.max_weight:
                violations.append(
                    ConstraintViolation(
                        constraint_name=self.name,
                        message=f"{symbol} weight exceeds position limit",
                        actual=weight,
                        limit=self.max_weight,
                    )
                )

        return tuple(violations)


@dataclass(frozen=True, slots=True)
class SectorLimitConstraint:
    """Maximum aggregate weight allowed in one sector."""

    max_weight: Decimal
    name: str = "sector_limit"

    def __post_init__(self) -> None:
        if self.max_weight <= Decimal("0"):
            raise ValueError("max_weight must be positive")

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        del current_weights, cash_weight

        sector_weights: dict[str, Decimal] = {}
        for symbol, weight in target_weights.items():
            sector = sector_by_symbol.get(symbol)
            if sector is None:
                continue
            sector_weights[sector] = sector_weights.get(sector, Decimal("0")) + weight

        violations: list[ConstraintViolation] = []
        for sector, weight in sector_weights.items():
            if weight > self.max_weight:
                violations.append(
                    ConstraintViolation(
                        constraint_name=self.name,
                        message=f"{sector} sector weight exceeds sector limit",
                        actual=weight,
                        limit=self.max_weight,
                    )
                )

        return tuple(violations)


@dataclass(frozen=True, slots=True)
class TurnoverConstraint:
    """Maximum absolute portfolio turnover allowed."""

    max_turnover: Decimal
    name: str = "turnover_limit"

    def __post_init__(self) -> None:
        if self.max_turnover < Decimal("0"):
            raise ValueError("max_turnover cannot be negative")

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        del sector_by_symbol, cash_weight

        symbols = set(target_weights) | set(current_weights)
        turnover = sum(
            abs(
                target_weights.get(symbol, Decimal("0"))
                - current_weights.get(symbol, Decimal("0"))
            )
            for symbol in symbols
        ) / Decimal("2")

        if turnover <= self.max_turnover:
            return ()

        return (
            ConstraintViolation(
                constraint_name=self.name,
                message="Expected turnover exceeds turnover limit",
                actual=turnover,
                limit=self.max_turnover,
            ),
        )


@dataclass(frozen=True, slots=True)
class CashReserveConstraint:
    """Minimum cash reserve required after optimization."""

    min_cash_weight: Decimal
    name: str = "cash_reserve"

    def __post_init__(self) -> None:
        if self.min_cash_weight < Decimal("0"):
            raise ValueError("min_cash_weight cannot be negative")

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        del target_weights, current_weights, sector_by_symbol

        if cash_weight >= self.min_cash_weight:
            return ()

        return (
            ConstraintViolation(
                constraint_name=self.name,
                message="Cash weight is below required reserve",
                actual=cash_weight,
                limit=self.min_cash_weight,
            ),
        )


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """Immutable collection of optimizer constraints."""

    constraints: tuple[PortfolioConstraint, ...] = ()

    def validate(
        self,
        *,
        target_weights: Mapping[str, Decimal],
        current_weights: Mapping[str, Decimal],
        sector_by_symbol: Mapping[str, str],
        cash_weight: Decimal,
    ) -> tuple[ConstraintViolation, ...]:
        """Validate all constraints and return every violation."""

        violations: list[ConstraintViolation] = []

        for constraint in self.constraints:
            violations.extend(
                constraint.validate(
                    target_weights=target_weights,
                    current_weights=current_weights,
                    sector_by_symbol=sector_by_symbol,
                    cash_weight=cash_weight,
                )
            )

        return tuple(violations)
