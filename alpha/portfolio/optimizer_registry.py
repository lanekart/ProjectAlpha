"""Optimizer registration and discovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from alpha.portfolio.black_litterman_optimizer import BlackLittermanOptimizer
from alpha.portfolio.equal_weight_optimizer import EqualWeightOptimizer
from alpha.portfolio.inverse_volatility_optimizer import InverseVolatilityOptimizer
from alpha.portfolio.maximum_sharpe_optimizer import MaximumSharpeOptimizer
from alpha.portfolio.minimum_variance_optimizer import MinimumVarianceOptimizer
from alpha.portfolio.optimizer import Optimizer
from alpha.portfolio.risk_parity_optimizer import RiskParityOptimizer

type OptimizerType = type[Optimizer]


@dataclass(slots=True)
class OptimizerRegistry:
    """Registry of named optimizer implementations."""

    _optimizers: dict[str, OptimizerType] = field(default_factory=dict)

    def register(self, name: str, optimizer_type: OptimizerType) -> None:
        """Register an optimizer implementation."""

        normalized_name = self._normalize_name(name)
        if normalized_name in self._optimizers:
            raise ValueError(f"optimizer already registered: {normalized_name}")

        self._optimizers[normalized_name] = optimizer_type

    def get(self, name: str) -> OptimizerType:
        """Return optimizer type for name."""

        normalized_name = self._normalize_name(name)
        try:
            return self._optimizers[normalized_name]
        except KeyError as exc:
            raise KeyError(f"unknown optimizer: {normalized_name}") from exc

    def contains(self, name: str) -> bool:
        """Return whether optimizer name is registered."""

        return self._normalize_name(name) in self._optimizers

    def names(self) -> tuple[str, ...]:
        """Return registered optimizer names."""

        return tuple(sorted(self._optimizers))

    def registered(self) -> Mapping[str, OptimizerType]:
        """Return immutable registered optimizer mapping."""

        return MappingProxyType(dict(self._optimizers))

    def _normalize_name(self, name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("optimizer name cannot be empty")
        return normalized_name


def default_optimizer_registry() -> OptimizerRegistry:
    """Build registry with first-party optimizers."""

    registry = OptimizerRegistry()
    registry.register("equal_weight", EqualWeightOptimizer)
    registry.register("inverse_volatility", InverseVolatilityOptimizer)
    registry.register("risk_parity", RiskParityOptimizer)
    registry.register("minimum_variance", MinimumVarianceOptimizer)
    registry.register("maximum_sharpe", MaximumSharpeOptimizer)
    registry.register("black_litterman", BlackLittermanOptimizer)
    return registry
