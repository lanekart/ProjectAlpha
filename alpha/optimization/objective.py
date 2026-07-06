"""Objective function protocol."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


class Objective(Protocol):
    """Protocol for portfolio objective functions."""

    @property
    def name(self) -> str:
        """Return objective name."""

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        """Evaluate target weights against the objective."""
