from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpha.live.bar_builder import LiveBarBuilder
from alpha.live.health import FeedHealthEngine
from alpha.live.latency import LatencyMonitor
from alpha.live.models import (
    FeedHealthSnapshot,
    InstrumentSubscription,
    LatencySummary,
    LiveFeedStatus,
    LiveOHLCVBar,
    LiveRiskWarning,
    TickQualityAssessment,
)
from alpha.live.providers import LiveMarketDataProvider
from alpha.live.quality import TickQualityEngine
from alpha.live.registry import LiveInstrumentRegistry
from alpha.live.risk import LiveRiskContext, LiveRiskEngine
from alpha.live.session import MarketSessionEngine


@dataclass(frozen=True, slots=True)
class LiveMonitorSnapshot:
    symbol: str
    price: Decimal
    volume: Decimal
    vwap: Decimal | None
    bar_started_at: datetime
    feed_status: LiveFeedStatus
    stale: bool
    action_now: str
    tick_count: int = 0
    bar_count: int = 0
    feed_health: FeedHealthSnapshot | None = None
    tick_quality: TickQualityAssessment | None = None
    latency: LatencySummary | None = None
    warnings: tuple[LiveRiskWarning, ...] = ()


async def run_live_monitor(
    *,
    provider: LiveMarketDataProvider,
    subscriptions: tuple[InstrumentSubscription, ...],
    max_ticks: int | None = None,
) -> tuple[LiveMonitorSnapshot, ...]:
    one_minute = LiveBarBuilder(timeframe_minutes=1)
    five_minute = LiveBarBuilder(timeframe_minutes=5)
    health = FeedHealthEngine(provider_name=provider.__class__.__name__)
    quality = TickQualityEngine(subscriptions=subscriptions)
    latency = LatencyMonitor()
    session = MarketSessionEngine()
    registry = LiveInstrumentRegistry(subscriptions)
    risk = LiveRiskEngine()
    previous_bar_by_symbol: dict[str, LiveOHLCVBar] = {}
    await provider.connect()
    now = _now_from_provider(provider)
    health.mark_connected(authenticated=True, observed_at=now)
    await provider.subscribe(subscriptions)
    health.mark_subscribed()
    snapshots: list[LiveMonitorSnapshot] = []
    async for tick in provider.ticks():
        tick_quality = quality.validate_tick(tick)
        if tick_quality.status.value == "INVALID":
            continue
        health.mark_tick(observed_at=tick.observed_at)
        one_minute_bar = one_minute.update(tick)
        five_minute.update(tick)
        health.mark_bar(observed_at=one_minute_bar.started_at)
        latency.record_from_tick(
            tick=tick,
            indicator_completion_timestamp=tick.observed_at,
            recommendation_completion_timestamp=tick.observed_at,
        )
        health_snapshot = health.snapshot(observed_at=tick.observed_at)
        latency_summary = latency.summary()
        session_state = session.state_at(tick.observed_at)
        registry.update_tick(
            tick,
            session=session_state,
            feed_health=health_snapshot,
            latency=latency_summary,
            observed_at=tick.observed_at,
        )
        registry.update_bar(one_minute_bar)
        warnings = risk.evaluate(
            LiveRiskContext(
                tick=tick,
                quote=None,
                bar=one_minute_bar,
                previous_tick=None,
                previous_bar=previous_bar_by_symbol.get(tick.symbol),
                feed_health=health_snapshot,
                observed_at=tick.observed_at,
            )
        )
        previous_bar_by_symbol[tick.symbol] = one_minute_bar
        state = registry.state(tick.symbol)
        snapshots.append(
            _snapshot(
                provider=provider,
                bar=one_minute_bar,
                health=health_snapshot,
                tick_quality=tick_quality,
                latency=latency_summary,
                warnings=warnings,
                tick_count=state.tick_count if state is not None else 0,
                bar_count=state.bar_count if state is not None else 0,
            )
        )
        if max_ticks is not None and len(snapshots) >= max_ticks:
            break
    await provider.close()
    return tuple(snapshots)


def _snapshot(
    *,
    provider: LiveMarketDataProvider,
    bar: LiveOHLCVBar,
    health: FeedHealthSnapshot | None = None,
    tick_quality: TickQualityAssessment | None = None,
    latency: LatencySummary | None = None,
    warnings: tuple[LiveRiskWarning, ...] = (),
    tick_count: int = 0,
    bar_count: int = 0,
) -> LiveMonitorSnapshot:
    return LiveMonitorSnapshot(
        symbol=bar.symbol,
        price=bar.close_price,
        volume=bar.volume,
        vwap=bar.vwap,
        bar_started_at=bar.started_at,
        feed_status=provider.status,
        stale=provider.is_stale(now=bar.started_at),
        action_now="Live recommendation updates pending strategy engine integration.",
        tick_count=tick_count,
        bar_count=bar_count,
        feed_health=health,
        tick_quality=tick_quality,
        latency=latency,
        warnings=warnings,
    )


def _now_from_provider(provider: LiveMarketDataProvider) -> datetime:
    return datetime.now().astimezone()
