from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from alpha.market.bar import Bar
from alpha.market.timeframe import Timeframe


@dataclass(frozen=True, slots=True)
class Tick:
    """
    Immutable market tick.

    Used as input for bar aggregation.
    """

    symbol: str
    price: Decimal
    volume: int
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if self.price <= Decimal("0"):
            raise ValueError("tick price must be > 0")

        if self.volume < 0:
            raise ValueError("tick volume cannot be negative")

        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")


@dataclass(slots=True)
class BarBuilder:
    """
    Stateful OHLCV bar aggregator for a single symbol + timeframe.
    """

    symbol: str
    timeframe: Timeframe

    _current_bar: Bar | None = field(default=None, init=False)
    _bars: list[Bar] = field(default_factory=list, init=False)

    def update(self, tick: Tick) -> None:
        if tick.symbol != self.symbol:
            raise ValueError("symbol mismatch")

        if self._current_bar is None:
            self._start_new_bar(tick)
            return

        if self._is_new_bar(tick.timestamp):
            self._finalize_bar()
            self._start_new_bar(tick)
            return

        self._update_bar(tick)

    def bars(self) -> tuple[Bar, ...]:
        return tuple(self._bars)

    def flush(self) -> tuple[Bar, ...]:
        if self._current_bar is not None:
            self._finalize_bar()

        return tuple(self._bars)

    def _start_new_bar(self, tick: Tick) -> None:
        self._current_bar = Bar(
            symbol=tick.symbol,
            timeframe=self.timeframe,
            timestamp=tick.timestamp,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
        )

    def _update_bar(self, tick: Tick) -> None:
        current = self._current_bar

        if current is None:
            return

        self._current_bar = Bar(
            symbol=current.symbol,
            timeframe=current.timeframe,
            timestamp=current.timestamp,
            open=current.open,
            high=max(current.high, tick.price),
            low=min(current.low, tick.price),
            close=tick.price,
            volume=current.volume + tick.volume,
        )

    def _finalize_bar(self) -> None:
        if self._current_bar is not None:
            self._bars.append(self._current_bar)
            self._current_bar = None

    def _is_new_bar(self, timestamp: datetime) -> bool:
        if self._current_bar is None:
            return True

        delta = timestamp - self._current_bar.timestamp

        return delta.total_seconds() >= self.timeframe.seconds
