from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """Immutable metadata describing a strategy available to the platform."""

    name: str
    display_name: str
    description: str
    supports_backtest: bool
    supports_signal_generation: bool
    minimum_history_days: int

    def __post_init__(self) -> None:
        normalized_name = self.name.strip().lower()
        normalized_display_name = self.display_name.strip()
        normalized_description = self.description.strip()

        if not normalized_name:
            raise ValueError("strategy name cannot be empty")
        if not normalized_display_name:
            raise ValueError("strategy display name cannot be empty")
        if not normalized_description:
            raise ValueError("strategy description cannot be empty")
        if self.minimum_history_days <= 0:
            raise ValueError("minimum history days must be positive")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "display_name", normalized_display_name)
        object.__setattr__(self, "description", normalized_description)


@dataclass(frozen=True, slots=True)
class StrategyRegistry:
    """Deterministic immutable strategy registry."""

    _strategies: Mapping[str, StrategyDefinition]

    def __init__(self, strategies: Iterable[StrategyDefinition]) -> None:
        normalized: dict[str, StrategyDefinition] = {}
        for strategy in strategies:
            if strategy.name in normalized:
                raise ValueError(f"duplicate strategy registered: {strategy.name}")
            normalized[strategy.name] = strategy

        sorted_strategies = dict(sorted(normalized.items()))
        object.__setattr__(
            self,
            "_strategies",
            MappingProxyType(sorted_strategies),
        )

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return name.strip().lower() in self._strategies

    def __iter__(self) -> Iterator[StrategyDefinition]:
        return iter(self._strategies.values())

    def __len__(self) -> int:
        return len(self._strategies)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._strategies)

    def get(self, name: str) -> StrategyDefinition:
        normalized_name = name.strip().lower()
        if normalized_name not in self._strategies:
            raise KeyError(f"unknown strategy: {name}")
        return self._strategies[normalized_name]

    def backtestable(self) -> tuple[StrategyDefinition, ...]:
        return tuple(strategy for strategy in self if strategy.supports_backtest)

    def signal_generating(self) -> tuple[StrategyDefinition, ...]:
        return tuple(
            strategy for strategy in self if strategy.supports_signal_generation
        )


def default_strategy_registry() -> StrategyRegistry:
    """Return the deterministic built-in strategy registry."""

    return StrategyRegistry(
        (
            StrategyDefinition(
                name="momentum",
                display_name="Momentum",
                description=(
                    "Ranks liquid NSE equities using deterministic momentum "
                    "signals from the normalized daily market data pipeline."
                ),
                supports_backtest=True,
                supports_signal_generation=True,
                minimum_history_days=20,
            ),
        )
    )
