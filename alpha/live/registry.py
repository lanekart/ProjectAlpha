from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpha.live.models import (
    FeedHealthSnapshot,
    InstrumentSubscription,
    LatencySummary,
    LiveOHLCVBar,
    LiveTick,
    MarketSessionState,
)


@dataclass(frozen=True, slots=True)
class InstrumentState:
    symbol: str
    subscribed: bool
    last_tick: LiveTick | None
    last_bar: LiveOHLCVBar | None
    tick_count: int
    bar_count: int
    vwap: Decimal | None
    current_session: MarketSessionState
    feed_quality: Decimal | None
    latency: LatencySummary | None
    staleness_seconds: Decimal | None


class LiveInstrumentRegistry:
    def __init__(self, subscriptions: tuple[InstrumentSubscription, ...]) -> None:
        self._states = {
            subscription.symbol: InstrumentState(
                symbol=subscription.symbol,
                subscribed=True,
                last_tick=None,
                last_bar=None,
                tick_count=0,
                bar_count=0,
                vwap=None,
                current_session=MarketSessionState.UNKNOWN,
                feed_quality=None,
                latency=None,
                staleness_seconds=None,
            )
            for subscription in subscriptions
        }

    def update_tick(
        self,
        tick: LiveTick,
        *,
        session: MarketSessionState,
        feed_health: FeedHealthSnapshot,
        latency: LatencySummary,
        observed_at: datetime,
    ) -> None:
        state = self._state(tick.symbol)
        self._states[tick.symbol] = InstrumentState(
            symbol=tick.symbol,
            subscribed=state.subscribed,
            last_tick=tick,
            last_bar=state.last_bar,
            tick_count=state.tick_count + 1,
            bar_count=state.bar_count,
            vwap=state.vwap,
            current_session=session,
            feed_quality=feed_health.feed_quality_score,
            latency=latency,
            staleness_seconds=_staleness(tick.observed_at, observed_at),
        )

    def update_bar(self, bar: LiveOHLCVBar) -> None:
        state = self._state(bar.symbol)
        self._states[bar.symbol] = InstrumentState(
            symbol=bar.symbol,
            subscribed=state.subscribed,
            last_tick=state.last_tick,
            last_bar=bar,
            tick_count=state.tick_count,
            bar_count=state.bar_count + 1,
            vwap=bar.vwap,
            current_session=state.current_session,
            feed_quality=state.feed_quality,
            latency=state.latency,
            staleness_seconds=state.staleness_seconds,
        )

    def states(self) -> tuple[InstrumentState, ...]:
        return tuple(self._states[symbol] for symbol in sorted(self._states))

    def state(self, symbol: str) -> InstrumentState | None:
        return self._states.get(symbol.strip().upper())

    def _state(self, symbol: str) -> InstrumentState:
        normalized = symbol.strip().upper()
        state = self._states.get(normalized)
        if state is not None:
            return state
        state = InstrumentState(
            symbol=normalized,
            subscribed=False,
            last_tick=None,
            last_bar=None,
            tick_count=0,
            bar_count=0,
            vwap=None,
            current_session=MarketSessionState.UNKNOWN,
            feed_quality=None,
            latency=None,
            staleness_seconds=None,
        )
        self._states[normalized] = state
        return state


def _staleness(last_tick_at: datetime, observed_at: datetime) -> Decimal:
    return Decimal(str((observed_at - last_tick_at).total_seconds())).quantize(
        Decimal("0.01")
    )


__all__ = ["InstrumentState", "LiveInstrumentRegistry"]
