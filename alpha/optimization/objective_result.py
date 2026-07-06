"""Objective evaluation result value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class ObjectiveResult:
    """Immutable result produced by an objective evaluation."""

    name: str
    score: Decimal
    components: Mapping[str, Decimal] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("objective result name cannot be empty")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
