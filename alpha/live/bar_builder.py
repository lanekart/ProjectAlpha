from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from alpha.live.models import LiveOHLCVBar, LiveTick


@dataclass(slots=True)
class _MutableBar:
    symbol: str
    started_at: datetime
    timeframe_minutes: int
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    turnover: Decimal

    def update(self, tick: LiveTick) -> None:
        self.high_price = max(self.high_price, tick.price)
        self.low_price = min(self.low_price, tick.price)
        self.close_price = tick.price
        self.volume += tick.volume
        self.turnover += tick.price * tick.volume

    def freeze(self) -> LiveOHLCVBar:
        vwap = self.turnover / self.volume if self.volume > Decimal("0") else None
        return LiveOHLCVBar(
            symbol=self.symbol,
            started_at=self.started_at,
            timeframe_minutes=self.timeframe_minutes,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume,
            vwap=vwap,
        )


@dataclass(slots=True)
class LiveBarBuilder:
    timeframe_minutes: int
    _bars: dict[tuple[str, datetime], _MutableBar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeframe_minutes <= 0:
            raise ValueError("timeframe must be positive")

    def update(self, tick: LiveTick) -> LiveOHLCVBar:
        bucket = self._bucket_start(tick.observed_at)
        key = (tick.symbol, bucket)
        bar = self._bars.get(key)
        if bar is None:
            bar = _MutableBar(
                symbol=tick.symbol,
                started_at=bucket,
                timeframe_minutes=self.timeframe_minutes,
                open_price=tick.price,
                high_price=tick.price,
                low_price=tick.price,
                close_price=tick.price,
                volume=tick.volume,
                turnover=tick.price * tick.volume,
            )
            self._bars[key] = bar
        else:
            bar.update(tick)
        return bar.freeze()

    def _bucket_start(self, observed_at: datetime) -> datetime:
        minute = (observed_at.minute // self.timeframe_minutes) * self.timeframe_minutes
        return observed_at.replace(minute=minute, second=0, microsecond=0)

    def completed_before(self, observed_at: datetime) -> tuple[LiveOHLCVBar, ...]:
        cutoff = self._bucket_start(observed_at)
        completed: list[LiveOHLCVBar] = []
        for key, bar in tuple(self._bars.items()):
            if bar.started_at + timedelta(minutes=self.timeframe_minutes) <= cutoff:
                completed.append(bar.freeze())
                del self._bars[key]
        return tuple(sorted(completed, key=lambda bar: (bar.symbol, bar.started_at)))
