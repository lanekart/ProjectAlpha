from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from alpha.cli import _parse_live_symbols, _print_live_snapshot, app
from alpha.live import (
    FeedHealthEngine,
    FeedHealthStatus,
    InstrumentSubscription,
    LatencyMonitor,
    LiveBarBuilder,
    LiveInstrumentRegistry,
    LiveRiskContext,
    LiveRiskEngine,
    LiveTick,
    MarketSessionEngine,
    TickQualityEngine,
    TickQualityStatus,
    run_live_monitor,
)
from alpha.live.models import LiveFeedStatus, MarketSessionState
from alpha.live.upstox import UpstoxLiveMarketDataProvider


def test_live_bar_builder_builds_one_minute_ohlcv_and_vwap() -> None:
    builder = LiveBarBuilder(timeframe_minutes=1)
    started = datetime(2026, 7, 9, 9, 15, 1, tzinfo=UTC)

    builder.update(
        LiveTick(
            symbol="kalyankjil",
            price=Decimal("100"),
            volume=Decimal("10"),
            observed_at=started,
        )
    )
    bar = builder.update(
        LiveTick(
            symbol="KALYANKJIL",
            price=Decimal("104"),
            volume=Decimal("30"),
            observed_at=started + timedelta(seconds=20),
        )
    )

    assert bar.symbol == "KALYANKJIL"
    assert bar.open_price == Decimal("100")
    assert bar.high_price == Decimal("104")
    assert bar.low_price == Decimal("100")
    assert bar.close_price == Decimal("104")
    assert bar.volume == Decimal("40")
    assert bar.vwap == Decimal("103")


def test_live_bar_builder_emits_completed_bars() -> None:
    builder = LiveBarBuilder(timeframe_minutes=5)
    observed_at = datetime(2026, 7, 9, 9, 16, tzinfo=UTC)

    builder.update(
        LiveTick(
            symbol="PCJEWELLER",
            price=Decimal("20"),
            volume=Decimal("100"),
            observed_at=observed_at,
        )
    )

    completed = builder.completed_before(datetime(2026, 7, 9, 9, 25, tzinfo=UTC))

    assert len(completed) == 1
    assert completed[0].started_at == datetime(2026, 7, 9, 9, 15, tzinfo=UTC)


def test_upstox_provider_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)

    provider = UpstoxLiveMarketDataProvider.from_environment()

    assert provider.configured() is False
    assert provider.status is LiveFeedStatus.DISCONNECTED


def test_upstox_stale_feed_detection() -> None:
    provider = UpstoxLiveMarketDataProvider(access_token="token")
    provider._status = LiveFeedStatus.CONNECTED
    provider._last_message_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)

    assert provider.is_stale(now=datetime(2026, 7, 9, 9, 15, 20, tzinfo=UTC))


def test_live_cli_does_not_fake_live_data_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    result = CliRunner().invoke(
        app,
        ["live", "--symbols", "KALYANKJIL,PCJEWELLER"],
    )

    assert result.exit_code == 0
    assert "Live feed unavailable" in result.stdout
    assert "No live recommendations generated." in result.stdout


def test_live_symbol_parser_accepts_comma_separated_symbols() -> None:
    assert _parse_live_symbols(
        symbols=["KALYANKJIL,PCJEWELLER,CUPID"],
        repeated_symbols=None,
    ) == ("KALYANKJIL", "PCJEWELLER", "CUPID")


def test_live_symbol_parser_accepts_repeated_symbol_flags() -> None:
    assert _parse_live_symbols(
        symbols=None,
        repeated_symbols=["KALYANKJIL", "PCJEWELLER"],
    ) == ("KALYANKJIL", "PCJEWELLER")


def test_live_symbol_parser_preserves_order_and_deduplicates() -> None:
    assert _parse_live_symbols(
        symbols=["KALYANKJIL,PCJEWELLER"],
        repeated_symbols=["KALYANKJIL", "CUPID"],
    ) == ("KALYANKJIL", "PCJEWELLER", "CUPID")


def test_live_symbol_parser_rejects_empty_symbols() -> None:
    with pytest.raises(Exception, match="Provide at least one symbol"):
        _parse_live_symbols(symbols=[" , "], repeated_symbols=[])


def test_live_monitor_uses_fake_provider_and_emits_status() -> None:
    provider = _FakeLiveProvider(
        ticks=(
            LiveTick(
                symbol="KALYANKJIL",
                price=Decimal("100"),
                volume=Decimal("25"),
                observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
            ),
        )
    )

    snapshots = asyncio.run(
        run_live_monitor(
            provider=provider,
            subscriptions=(
                InstrumentSubscription(
                    symbol="KALYANKJIL",
                    instrument_key="NSE_EQ|KALYANKJIL",
                ),
            ),
            max_ticks=1,
        )
    )

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "KALYANKJIL"
    assert snapshots[0].price == Decimal("100")
    assert snapshots[0].volume == Decimal("25")
    assert snapshots[0].feed_status is LiveFeedStatus.CONNECTED


def test_instrument_subscription_normalizes_symbol() -> None:
    subscription = InstrumentSubscription(
        symbol=" kalyankjil ",
        instrument_key="NSE_EQ|KALYANKJIL",
    )

    assert subscription.symbol == "KALYANKJIL"


def test_feed_health_detects_heartbeat_timeout() -> None:
    engine = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    engine.mark_connected(authenticated=True, observed_at=observed_at)
    engine.mark_subscribed()
    engine.mark_tick(observed_at=observed_at)

    snapshot = engine.snapshot(observed_at=observed_at + timedelta(seconds=40))

    assert snapshot.status is FeedHealthStatus.STALE
    assert snapshot.heartbeat_age_seconds == Decimal("40.00")


def test_feed_health_reports_reconnect_state() -> None:
    engine = FeedHealthEngine(provider_name="Fake")

    engine.mark_reconnecting()
    snapshot = engine.snapshot(observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC))

    assert snapshot.status is FeedHealthStatus.RECONNECTING
    assert snapshot.reconnect_attempts == 1


def test_tick_quality_detects_duplicate_ticks() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))
    tick = LiveTick(
        symbol="AAA",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert engine.validate_tick(tick).status is TickQualityStatus.VALID
    duplicate = engine.validate_tick(tick)

    assert duplicate.status is TickQualityStatus.SUSPECT
    assert "duplicate timestamp" in duplicate.reasons
    assert "duplicate price" in duplicate.reasons


def test_tick_quality_rejects_invalid_ticks() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))

    assessment = engine.validate_fields(
        symbol="ZZZ",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert assessment.status is TickQualityStatus.INVALID
    assert "invalid instrument" in assessment.reasons


def test_tick_quality_rejects_zero_price_and_negative_volume() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))

    assessment = engine.validate_fields(
        symbol="AAA",
        price=Decimal("0"),
        volume=Decimal("-1"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert assessment.status is TickQualityStatus.INVALID
    assert "zero price" in assessment.reasons
    assert "negative volume" in assessment.reasons
    assert engine.statistics.invalid_ticks == 1


def test_latency_monitor_calculates_rolling_metrics() -> None:
    monitor = LatencyMonitor(window_size=5)
    exchange = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)

    monitor.record(
        symbol="AAA",
        exchange_timestamp=exchange,
        provider_timestamp=exchange + timedelta(milliseconds=100),
        alpha_receive_timestamp=exchange + timedelta(milliseconds=200),
        indicator_completion_timestamp=exchange + timedelta(milliseconds=300),
        recommendation_completion_timestamp=exchange + timedelta(milliseconds=500),
    )
    summary = monitor.summary()

    assert summary.sample_count == 1
    assert summary.rolling_average_seconds == Decimal("0.5000")
    assert summary.rolling_p95_seconds == Decimal("0.5000")


def test_feed_degradation_when_subscription_missing() -> None:
    engine = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    engine.mark_connected(authenticated=True, observed_at=observed_at)

    snapshot = engine.snapshot(observed_at=observed_at)

    assert snapshot.status is FeedHealthStatus.DEGRADED


def test_market_session_transitions_and_weekend_holiday_detection() -> None:
    holiday = date(2026, 7, 10)
    engine = MarketSessionEngine(holidays=frozenset({holiday}))

    assert (
        engine.state_at(datetime(2026, 7, 9, 9, 5, tzinfo=UTC))
        is MarketSessionState.PRE_OPEN
    )
    assert (
        engine.state_at(datetime(2026, 7, 9, 10, 30, tzinfo=UTC))
        is MarketSessionState.MID_SESSION
    )
    assert (
        engine.state_at(datetime(2026, 7, 9, 14, 45, tzinfo=UTC))
        is MarketSessionState.POWER_HOUR
    )
    assert (
        engine.state_at(datetime(2026, 7, 11, 10, 0, tzinfo=UTC))
        is MarketSessionState.WEEKEND
    )
    assert (
        engine.state_at(datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        is MarketSessionState.HOLIDAY
    )
    assert engine.is_trading(datetime(2026, 7, 9, 10, 30, tzinfo=UTC))


def test_registry_updates_tick_bar_and_feed_quality() -> None:
    registry = LiveInstrumentRegistry((_subscription("AAA"),))
    health = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    health.mark_connected(authenticated=True, observed_at=observed_at)
    health.mark_subscribed()
    tick = LiveTick("AAA", Decimal("100"), Decimal("10"), observed_at)
    bar = LiveBarBuilder(timeframe_minutes=1).update(tick)
    snapshot = health.snapshot(observed_at=observed_at)

    registry.update_tick(
        tick,
        session=MarketSessionState.OPEN,
        feed_health=snapshot,
        latency=LatencyMonitor().summary(),
        observed_at=observed_at,
    )
    registry.update_bar(bar)

    state = registry.state("AAA")
    assert state is not None
    assert state.tick_count == 1
    assert state.bar_count == 1
    assert state.feed_quality == Decimal("100")


def test_live_risk_warnings_explain_stale_feed() -> None:
    health = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    health.mark_connected(authenticated=True, observed_at=observed_at)
    health.mark_subscribed()
    health.mark_tick(observed_at=observed_at)
    stale_snapshot = health.snapshot(observed_at=observed_at + timedelta(seconds=45))

    warnings = LiveRiskEngine().evaluate(
        LiveRiskContext(
            tick=None,
            quote=None,
            bar=None,
            previous_tick=None,
            previous_bar=None,
            feed_health=stale_snapshot,
            observed_at=observed_at + timedelta(seconds=45),
        )
    )

    assert warnings[0].message == "Feed stale for 45.00 seconds"
    assert warnings[0].why
    assert warnings[0].operator_action


def test_live_cli_compact_snapshot_output(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _fake_snapshot()

    _print_live_snapshot(snapshot, verbose=False)

    output = capsys.readouterr().out
    assert "Provider" in output
    assert "Feed Quality:" in output
    assert "Risk Flags:" in output
    assert "Tick Diagnostics" not in output


def test_live_cli_verbose_snapshot_output(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _fake_snapshot()

    _print_live_snapshot(snapshot, verbose=True)

    output = capsys.readouterr().out
    assert "Tick Diagnostics" in output
    assert "Latency Breakdown" in output
    assert "Health History" in output


class _FakeLiveProvider:
    def __init__(self, *, ticks: tuple[LiveTick, ...]) -> None:
        self._ticks = ticks
        self._status = LiveFeedStatus.DISCONNECTED
        self._subscriptions: tuple[InstrumentSubscription, ...] = ()

    @property
    def status(self) -> LiveFeedStatus:
        return self._status

    @property
    def session_state(self) -> MarketSessionState:
        return MarketSessionState.OPEN

    def is_stale(self, *, now: datetime) -> bool:
        return False

    async def connect(self) -> None:
        self._status = LiveFeedStatus.CONNECTED

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None:
        self._subscriptions = tuple(subscriptions)

    async def ticks(self) -> AsyncIterator[LiveTick]:
        for tick in self._ticks:
            yield tick

    async def close(self) -> None:
        self._status = LiveFeedStatus.DISCONNECTED


def _subscription(symbol: str) -> InstrumentSubscription:
    return InstrumentSubscription(symbol=symbol, instrument_key=f"NSE_EQ|{symbol}")


def _fake_snapshot():
    provider = _FakeLiveProvider(ticks=())
    provider._status = LiveFeedStatus.CONNECTED
    tick = LiveTick(
        symbol="AAA",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )
    bar = LiveBarBuilder(timeframe_minutes=1).update(tick)
    snapshots = asyncio.run(
        run_live_monitor(
            provider=_FakeLiveProvider(ticks=(tick,)),
            subscriptions=(_subscription("AAA"),),
            max_ticks=1,
        )
    )
    assert bar.symbol == "AAA"
    return snapshots[0]
