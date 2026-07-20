from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from alpha.historical_truth.models import ArchiveDataset, ArchiveRequest


class ArchiveDatasetPlugin(Protocol):
    """Plans official archive requests for one dataset."""

    @property
    def dataset(self) -> ArchiveDataset: ...

    @property
    def exchange(self) -> str: ...

    def plan(self, start: date, end: date) -> tuple[ArchiveRequest, ...]: ...


@dataclass(slots=True)
class DatasetRegistry:
    """Explicit registry; duplicate exchange/dataset registrations fail closed."""

    _plugins: dict[tuple[str, ArchiveDataset], ArchiveDatasetPlugin]

    def __init__(self) -> None:
        self._plugins = {}

    def register(self, plugin: ArchiveDatasetPlugin) -> None:
        key = (plugin.exchange.lower(), plugin.dataset)
        if key in self._plugins:
            raise ValueError(f"dataset already registered: {key[0]}/{key[1].value}")
        self._plugins[key] = plugin

    def get(self, exchange: str, dataset: ArchiveDataset) -> ArchiveDatasetPlugin:
        key = (exchange.lower(), dataset)
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(
                f"dataset is not registered: {key[0]}/{key[1].value}"
            ) from exc

    def plugins(self) -> tuple[ArchiveDatasetPlugin, ...]:
        return tuple(
            self._plugins[key]
            for key in sorted(self._plugins, key=lambda item: (item[0], item[1].value))
        )
