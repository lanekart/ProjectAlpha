from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from alpha.market.bar import Bar
from alpha.market.timeframe import Timeframe


@dataclass(slots=True)
class Tick:
    """
    Immutable market tick.

    Used as input for bar aggregation.
    """

    symbol: str
    price: Decimal
    volume: Decimal
    timestamp: datetime


@dataclass(slots=True)
class BarBuilder:
    """
    Stateful OHLCV bar aggregator for a single symbol + timeframe.

    Deterministic:
    - same tick stream → same bars always
    """

    symbol: str
    timeframe: Timeframe

    _current_bar: Bar | None = field(default=None, init=False)
    _bars: list[Bar] = field(default_factory=list, init=False)

    # -------------------------
    # Public API
    # -------------------------

    def update(self, tick: Tick) -> None:
        if tick.symbol != self.symbol:
            raise ValueError("symbol mismatch")

        if self._current_bar is None:
            self._start_new_bar(tick)
            return

        if self._is_new_bar(tick.timestamp):
            self._finalize_bar()
            self._start_new_bar(tick)
        else:
            self._update_bar(tick)

    def bars(self) -> tuple[Bar, ...]:
        return tuple(self._bars)

    def flush(self) -> tuple[Bar, ...]:
        if self._current_bar is not None:
            self._finalize_bar()
        return tuple(self._bars)

    # -------------------------
    # Internal logic
    # -------------------------

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
        b = self._current_bar
        if b is None:
            return

        self._current_bar = Bar(
            symbol=b.symbol,
            timeframe=b.timeframe,
            timestamp=b.timestamp,
            open=b.open,
            high=max(b.high, tick.price),
            low=min(b.low, tick.price),
            close=tick.price,
            volume=b.volume + tick.volume,
        )

    def _finalize_bar(self) -> None:
        if self._current_bar is not None:
            self._bars.append(self._current_bar)
            self._current_bar = None

    def _is_new_bar(self, ts: datetime) -> bool:
        if self._current_bar is None:
            return True

        # deterministic boundary: compare against bar start
        delta = ts - self._current_bar.timestamp
        return delta.total_seconds() >= self.timeframe.to_seconds()
