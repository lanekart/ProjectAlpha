"""Optimizer configuration value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from alpha.portfolio.constraints import ConstraintSet


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
    """Immutable configuration used to construct an optimizer by name."""

    name: str
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("optimizer name cannot be empty")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
