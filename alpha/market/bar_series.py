from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import overload

from alpha.market.bar import Bar
from alpha.market.timeframe import Timeframe


class BarSeries(Sequence[Bar]):
    __slots__ = (
        "_bars",
        "_initialized",
        "_symbol",
        "_timeframe",
        "_timestamps",
    )

    _bars: tuple[Bar, ...]
    _initialized: bool
    _symbol: str
    _timeframe: Timeframe
    _timestamps: tuple[datetime, ...]

    def __init__(self, bars: Sequence[Bar]) -> None:
        if not bars:
            raise ValueError("BarSeries cannot be empty")

        ordered = tuple(bars)
        symbol = ordered[0].symbol
        timeframe = ordered[0].timeframe
        timestamps: list[datetime] = []

        previous_timestamp: datetime | None = None

        for bar in ordered:
            if bar.symbol != symbol:
                raise ValueError("All bars must have same symbol")

            if bar.timeframe != timeframe:
                raise ValueError("All bars must have same timeframe")

            if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
                raise ValueError("Timestamps must be strictly increasing")

            timestamps.append(bar.timestamp)
            previous_timestamp = bar.timestamp

        object.__setattr__(self, "_bars", ordered)
        object.__setattr__(self, "_symbol", symbol)
        object.__setattr__(self, "_timeframe", timeframe)
        object.__setattr__(self, "_timestamps", tuple(timestamps))
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_initialized", False):
            raise TypeError("BarSeries is immutable")

        object.__setattr__(self, name, value)

    @property
    def bars(self) -> tuple[Bar, ...]:
        return self._bars

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    @property
    def timestamps(self) -> tuple[datetime, ...]:
        return self._timestamps

    @property
    def first(self) -> Bar:
        return self._bars[0]

    @property
    def last(self) -> Bar:
        return self._bars[-1]

    @property
    def start(self) -> datetime:
        return self.first.timestamp

    @property
    def end(self) -> datetime:
        return self.last.timestamp

    def head(self, n: int) -> BarSeries:
        if n <= 0:
            raise ValueError("n must be positive")

        return BarSeries(self._bars[:n])

    def tail(self, n: int) -> BarSeries:
        if n <= 0:
            raise ValueError("n must be positive")

        return BarSeries(self._bars[-n:])

    def between(self, start: datetime, end: datetime) -> BarSeries:
        left = bisect_left(self._timestamps, start)
        right = bisect_right(self._timestamps, end)

        if left >= right:
            raise ValueError("No bars in the given time range")

        return BarSeries(self._bars[left:right])

    def __len__(self) -> int:
        return len(self._bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)

    @overload
    def __getitem__(self, index: int) -> Bar: ...

    @overload
    def __getitem__(self, index: slice) -> BarSeries: ...

    def __getitem__(self, index: int | slice) -> Bar | BarSeries:
        if isinstance(index, slice):
            return BarSeries(self._bars[index])

        return self._bars[index]

    def __contains__(self, bar: object) -> bool:
        return bar in self._bars

    def __repr__(self) -> str:
        return (
            f"BarSeries(symbol={self.symbol!r}, "
            f"timeframe={self.timeframe!s}, "
            f"bars={len(self)})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BarSeries):
            return False

        return self._bars == other._bars

    def __hash__(self) -> int:
        return hash(self._bars)
