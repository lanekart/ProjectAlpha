from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class RollingWindow[T]:
    """
    Fixed-size rolling window.

    Deterministic structure used for:
    - indicators
    - feature engineering
    - streaming market state
    """

    size: int
    _data: deque[T]

    def __init__(self, size: int) -> None:
        if size <= 0:
            raise ValueError("window size must be positive")

        self.size = size
        self._data = deque()

    def add(self, item: T) -> None:
        self._data.append(item)

        if len(self._data) > self.size:
            self._data.popleft()

    def values(self) -> tuple[T, ...]:
        return tuple(self._data)

    def is_full(self) -> bool:
        return len(self._data) == self.size

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[T]:
        return iter(self._data)
