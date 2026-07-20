"""Registry for discoverable Project Alpha diagnostic engines."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from .base import DiagnosticEngine

EngineFactory = Callable[[], DiagnosticEngine]


class DiagnosticRegistry:
    """Maintain unique diagnostic engine factories by stable engine key."""

    def __init__(self) -> None:
        self._factories: dict[str, EngineFactory] = {}

    def register(self, engine_key: str, factory: EngineFactory) -> None:
        """Register a factory, rejecting accidental key replacement."""

        normalized_key = engine_key.strip()
        if not normalized_key:
            raise ValueError("engine_key must not be empty")
        if normalized_key in self._factories:
            raise ValueError(f"diagnostic engine {normalized_key!r} is already registered")
        self._factories[normalized_key] = factory

    def create(self, engine_key: str) -> DiagnosticEngine:
        """Instantiate a registered engine and verify its declared key."""

        try:
            factory = self._factories[engine_key]
        except KeyError as exc:
            raise KeyError(f"unknown diagnostic engine {engine_key!r}") from exc

        engine = factory()
        if engine.engine_key != engine_key:
            raise ValueError(
                f"factory registered as {engine_key!r} produced "
                f"engine {engine.engine_key!r}"
            )
        return engine

    def keys(self) -> tuple[str, ...]:
        """Return registered keys in deterministic order."""

        return tuple(sorted(self._factories))

    def __contains__(self, engine_key: object) -> bool:
        return engine_key in self._factories

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


registry = DiagnosticRegistry()
