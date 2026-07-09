from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from alpha.live.models import FeedHealthSnapshot, FeedHealthStatus


@dataclass(slots=True)
class FeedHealthEngine:
    provider_name: str
    stale_after: timedelta = timedelta(seconds=30)
    heartbeat_timeout: timedelta = timedelta(seconds=30)
    provider_connected: bool = False
    authenticated: bool = False
    subscribed: bool = False
    last_heartbeat_at: datetime | None = None
    last_tick_timestamp: datetime | None = None
    last_bar_timestamp: datetime | None = None
    reconnect_attempts: int = 0
    provider_latency_seconds: Decimal | None = None
    failed: bool = False
    reconnecting: bool = False

    def mark_connected(self, *, authenticated: bool, observed_at: datetime) -> None:
        self.provider_connected = True
        self.authenticated = authenticated
        self.failed = False
        self.reconnecting = False
        self.last_heartbeat_at = observed_at

    def mark_subscribed(self) -> None:
        self.subscribed = True

    def mark_heartbeat(
        self,
        *,
        observed_at: datetime,
        provider_latency_seconds: Decimal | None = None,
    ) -> None:
        self.last_heartbeat_at = observed_at
        self.provider_latency_seconds = provider_latency_seconds

    def mark_tick(self, *, observed_at: datetime) -> None:
        self.last_tick_timestamp = observed_at

    def mark_bar(self, *, observed_at: datetime) -> None:
        self.last_bar_timestamp = observed_at

    def mark_reconnecting(self) -> None:
        self.reconnecting = True
        self.reconnect_attempts += 1

    def mark_failed(self) -> None:
        self.failed = True
        self.provider_connected = False

    def snapshot(self, *, observed_at: datetime) -> FeedHealthSnapshot:
        heartbeat_age = _age_seconds(self.last_heartbeat_at, observed_at)
        stale_duration = _age_seconds(self.last_tick_timestamp, observed_at)
        reasons: list[str] = []

        status = FeedHealthStatus.CONNECTED
        if self.failed:
            status = FeedHealthStatus.FAILED
            reasons.append("Provider marked failed.")
        elif self.reconnecting:
            status = FeedHealthStatus.RECONNECTING
            reasons.append("Provider is reconnecting.")
        elif not self.provider_connected:
            status = FeedHealthStatus.DISCONNECTED
            reasons.append("Provider is disconnected.")
        elif heartbeat_age is not None and heartbeat_age > _seconds(
            self.heartbeat_timeout
        ):
            status = FeedHealthStatus.STALE
            reasons.append(f"Heartbeat stale for {heartbeat_age} seconds.")
        elif stale_duration is not None and stale_duration > _seconds(self.stale_after):
            status = FeedHealthStatus.STALE
            reasons.append(f"Feed stale for {stale_duration} seconds.")
        elif not self.authenticated or not self.subscribed:
            status = FeedHealthStatus.DEGRADED
            reasons.append("Provider is connected but not fully ready.")

        return FeedHealthSnapshot(
            provider_name=self.provider_name,
            status=status,
            provider_connected=self.provider_connected,
            authenticated=self.authenticated,
            subscribed=self.subscribed,
            heartbeat_received=self.last_heartbeat_at is not None,
            heartbeat_age_seconds=heartbeat_age,
            last_tick_timestamp=self.last_tick_timestamp,
            last_bar_timestamp=self.last_bar_timestamp,
            reconnect_attempts=self.reconnect_attempts,
            stale_duration_seconds=stale_duration,
            provider_latency_seconds=self.provider_latency_seconds,
            feed_quality_score=_quality_score(status),
            observed_at=observed_at,
            reasons=tuple(reasons),
        )


def _age_seconds(value: datetime | None, observed_at: datetime) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str((observed_at - value).total_seconds())).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _seconds(value: timedelta) -> Decimal:
    return Decimal(str(value.total_seconds())).quantize(Decimal("0.01"))


def _quality_score(status: FeedHealthStatus) -> Decimal:
    return {
        FeedHealthStatus.CONNECTED: Decimal("100"),
        FeedHealthStatus.DEGRADED: Decimal("70"),
        FeedHealthStatus.STALE: Decimal("40"),
        FeedHealthStatus.RECONNECTING: Decimal("30"),
        FeedHealthStatus.DISCONNECTED: Decimal("0"),
        FeedHealthStatus.FAILED: Decimal("0"),
    }[status]


__all__ = ["FeedHealthEngine"]
