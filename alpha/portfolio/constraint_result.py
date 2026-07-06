"""Typed result produced by portfolio constraint evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from alpha.portfolio.optimization_result import ConstraintViolation


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    """Immutable aggregate result for a constraint evaluation pass."""

    violations: tuple[ConstraintViolation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def passed(self) -> bool:
        """Return whether all evaluated constraints passed."""

        return len(self.violations) == 0

    @property
    def failed(self) -> bool:
        """Return whether at least one evaluated constraint failed."""

        return not self.passed
