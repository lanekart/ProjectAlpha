"""Typed diagnostics derived from optimizer inputs and results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from alpha.portfolio.optimization_result import ConstraintViolation, OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class OptimizationDiagnostics:
    """Immutable, typed diagnostics for an optimization run."""

    optimizer: str
    universe_size: int
    invested_weight: Decimal
    cash_weight: Decimal
    total_weight: Decimal
    expected_turnover: Decimal
    objective_scores: Mapping[str, Decimal] = field(default_factory=dict)
    violations_by_constraint: Mapping[str, tuple[ConstraintViolation, ...]] = field(
        default_factory=dict
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_optimizer = self.optimizer.strip()
        if not normalized_optimizer:
            raise ValueError("optimizer cannot be empty")
        if self.universe_size <= 0:
            raise ValueError("universe_size must be positive")
        if self.invested_weight < Decimal("0"):
            raise ValueError("invested_weight cannot be negative")
        if self.cash_weight < Decimal("0"):
            raise ValueError("cash_weight cannot be negative")
        if self.total_weight < Decimal("0"):
            raise ValueError("total_weight cannot be negative")
        if self.expected_turnover < Decimal("0"):
            raise ValueError("expected_turnover cannot be negative")

        object.__setattr__(self, "optimizer", normalized_optimizer)
        object.__setattr__(
            self,
            "objective_scores",
            MappingProxyType(dict(self.objective_scores)),
        )
        object.__setattr__(
            self,
            "violations_by_constraint",
            MappingProxyType(
                {
                    constraint_name: tuple(violations)
                    for constraint_name, violations in self.violations_by_constraint.items()
                }
            ),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def has_violations(self) -> bool:
        """Return whether any constraint violations were reported."""

        return any(self.violations_by_constraint.values())

    @classmethod
    def from_optimization(
        cls,
        *,
        optimization_input: OptimizationInput,
        result: OptimizationResult,
    ) -> OptimizationDiagnostics:
        """Build diagnostics from a completed optimization run."""

        return cls(
            optimizer=_extract_optimizer_name(result.metadata),
            universe_size=len(optimization_input.universe),
            invested_weight=result.invested_weight,
            cash_weight=result.cash_weight,
            total_weight=result.total_weight,
            expected_turnover=result.expected_turnover,
            objective_scores=_extract_objective_scores(result.metadata),
            violations_by_constraint=_group_violations(result.constraint_violations),
            metadata=result.metadata,
        )


def _extract_optimizer_name(metadata: Mapping[str, Any]) -> str:
    optimizer = metadata.get("optimizer")
    if isinstance(optimizer, str) and optimizer.strip():
        return optimizer
    return "unknown"


def _extract_objective_scores(metadata: Mapping[str, Any]) -> Mapping[str, Decimal]:
    objectives = metadata.get("objectives")
    if not isinstance(objectives, Mapping):
        return {}

    objective_scores: dict[str, Decimal] = {}
    for name, score in objectives.items():
        if isinstance(name, str) and isinstance(score, Decimal):
            objective_scores[name] = score

    return objective_scores


def _group_violations(
    violations: tuple[ConstraintViolation, ...],
) -> Mapping[str, tuple[ConstraintViolation, ...]]:
    grouped: dict[str, list[ConstraintViolation]] = {}

    for violation in violations:
        grouped.setdefault(violation.constraint_name, []).append(violation)

    return {
        constraint_name: tuple(constraint_violations)
        for constraint_name, constraint_violations in grouped.items()
    }
