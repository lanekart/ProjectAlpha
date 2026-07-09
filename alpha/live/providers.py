from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import Protocol

from alpha.live.models import (
    InstrumentSubscription,
    LiveFeedStatus,
    LiveTick,
    MarketSessionState,
)


class LiveMarketDataProvider(Protocol):
    @property
    def status(self) -> LiveFeedStatus: ...

    @property
    def session_state(self) -> MarketSessionState: ...

    def is_stale(self, *, now: datetime) -> bool: ...

    async def connect(self) -> None: ...

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None: ...

    def ticks(self) -> AsyncIterator[LiveTick]: ...

    async def close(self) -> None: ...
