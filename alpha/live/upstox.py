from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from alpha.live.models import (
    InstrumentSubscription,
    LiveFeedStatus,
    LiveTick,
    MarketSessionState,
)
from alpha.live.upstox_auth import (
    UpstoxAuthConfig,
    UpstoxAuthService,
    UpstoxTokenStatus,
)


@dataclass(slots=True)
class UpstoxLiveMarketDataProvider:
    access_token: str | None = None
    websocket_url: str = "wss://api.upstox.com/v3/feed/market-data-feed"
    stale_after_seconds: int = 15
    _status: LiveFeedStatus = LiveFeedStatus.DISCONNECTED
    _subscriptions: tuple[InstrumentSubscription, ...] = ()
    _last_message_at: datetime | None = None
    _closed: bool = field(default=False)

    @classmethod
    def from_environment(cls) -> UpstoxLiveMarketDataProvider:
        config = UpstoxAuthConfig.from_environment()
        return cls(
            access_token=config.access_token,
            websocket_url=config.websocket_url,
        )

    @property
    def status(self) -> LiveFeedStatus:
        return self._status

    @property
    def session_state(self) -> MarketSessionState:
        return MarketSessionState.UNKNOWN

    def configured(self) -> bool:
        return bool(self.access_token and self.access_token.strip())

    def is_stale(self, *, now: datetime) -> bool:
        if self._last_message_at is None:
            return self._status is LiveFeedStatus.CONNECTED
        return now - self._last_message_at > timedelta(seconds=self.stale_after_seconds)

    async def connect(self) -> None:
        if not self.configured():
            self._status = LiveFeedStatus.ERROR
            raise RuntimeError(
                "Upstox live provider is not configured. Set UPSTOX_ACCESS_TOKEN."
            )
        validation = UpstoxAuthService(
            config=UpstoxAuthConfig.from_environment()
        ).validate_token(remote=False)
        if validation.status is UpstoxTokenStatus.TOKEN_EXPIRED:
            self._status = LiveFeedStatus.ERROR
            raise RuntimeError("Upstox access token is expired.")
        self._status = LiveFeedStatus.CONNECTING
        self._status = LiveFeedStatus.CONNECTED

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None:
        self._subscriptions = tuple(subscriptions)

    def ticks(self) -> AsyncIterator[LiveTick]:
        if self._status is not LiveFeedStatus.CONNECTED:
            raise RuntimeError("Upstox live feed is not connected.")
        return _empty_ticks()

    async def close(self) -> None:
        self._closed = True
        self._status = LiveFeedStatus.DISCONNECTED


async def _empty_ticks() -> AsyncIterator[LiveTick]:
    if False:
        yield  # pragma: no cover
