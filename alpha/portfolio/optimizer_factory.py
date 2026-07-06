"""Optimizer factory construction."""

from __future__ import annotations

from dataclasses import dataclass, field

from alpha.portfolio.optimizer import Optimizer
from alpha.portfolio.optimizer_config import OptimizerConfig
from alpha.portfolio.optimizer_registry import (
    OptimizerRegistry,
    default_optimizer_registry,
)


@dataclass(frozen=True, slots=True)
class OptimizerFactory:
    """Factory that creates optimizers from immutable configuration."""

    registry: OptimizerRegistry = field(default_factory=default_optimizer_registry)

    def create(self, config: OptimizerConfig) -> Optimizer:
        """Create optimizer from config."""

        optimizer_type = self.registry.get(config.name)
        return optimizer_type(**config.parameters)
