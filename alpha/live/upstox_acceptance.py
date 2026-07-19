from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from alpha.live.bar_builder import LiveBarBuilder
from alpha.live.models import (
    InstrumentSubscription,
    LiveFeedStatus,
    LiveOHLCVBar,
    LiveTick,
    TickQualityStatus,
)
from alpha.live.quality import TickQualityEngine
from alpha.live.upstox import UpstoxLiveMarketDataProvider
from alpha.live.upstox_auth import (
    InstrumentResolutionStatus,
    UpstoxAuthService,
    UpstoxFeedAuthorization,
    UpstoxInstrumentResolution,
    UpstoxInstrumentResolver,
    UpstoxTokenStatus,
    UpstoxTokenValidation,
)


class UpstoxAcceptanceProviderMode(StrEnum):
    LIVE = "LIVE"


class UpstoxLiveAcceptanceClassification(StrEnum):
    LIVE_ACCEPTANCE_PASS = "LIVE_ACCEPTANCE_PASS"
    LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS = (
        "LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS"
    )
    NO_ACTIVE_TRADING_SEGMENTS = "NO_ACTIVE_TRADING_SEGMENTS"
    TOKEN_UNAVAILABLE = "TOKEN_UNAVAILABLE"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REMOTE_VALIDATION_FAILED = "TOKEN_REMOTE_VALIDATION_FAILED"
    FEED_AUTHORIZATION_FAILED = "FEED_AUTHORIZATION_FAILED"
    INSTRUMENT_NOT_RESOLVED = "INSTRUMENT_NOT_RESOLVED"
    LIVE_CONNECTION_FAILED = "LIVE_CONNECTION_FAILED"
    SUBSCRIPTION_FAILED = "SUBSCRIPTION_FAILED"
    LIVE_ACCEPTANCE_FAILED = "LIVE_ACCEPTANCE_FAILED"
    LIVE_ACCEPTANCE_TIMEOUT = "LIVE_ACCEPTANCE_TIMEOUT"
    LIVE_ACCEPTANCE_INTERRUPTED = "LIVE_ACCEPTANCE_INTERRUPTED"


class LiveAcceptanceProvider(Protocol):
    @property
    def status(self) -> LiveFeedStatus: ...

    async def connect(self) -> None: ...

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None: ...

    def ticks(self) -> AsyncIterator[LiveTick]: ...

    async def close(self) -> None: ...


class UpstoxAcceptanceAuth(Protocol):
    def load_metadata(self) -> object | None: ...

    def validate_token(self, *, remote: bool = True) -> UpstoxTokenValidation: ...

    def authorize_market_data_feed_v3(self) -> UpstoxFeedAuthorization: ...


@dataclass(frozen=True, slots=True)
class UpstoxLiveAcceptancePreflight:
    configuration_available: bool
    token_metadata_available: bool
    token_locally_unexpired: bool
    remote_token_validation_status: str
    feed_authorization_status: str
    selected_instrument_key: str
    registry_resolution_status: str
    resolved_symbol: str | None
    resolved_exchange: str | None
    max_events: int
    timeout_seconds: int
    order_apis_disabled: bool
    passed: bool
    failure_classification: UpstoxLiveAcceptanceClassification | None = None
    failure_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "configuration_available": self.configuration_available,
            "token_metadata_available": self.token_metadata_available,
            "token_locally_unexpired": self.token_locally_unexpired,
            "remote_token_validation_status": self.remote_token_validation_status,
            "feed_authorization_status": self.feed_authorization_status,
            "selected_instrument_key": self.selected_instrument_key,
            "registry_resolution_status": self.registry_resolution_status,
            "resolved_symbol": self.resolved_symbol,
            "resolved_exchange": self.resolved_exchange,
            "max_events": self.max_events,
            "timeout_seconds": self.timeout_seconds,
            "order_apis_disabled": self.order_apis_disabled,
            "passed": self.passed,
            "failure_classification": (
                None
                if self.failure_classification is None
                else self.failure_classification.value
            ),
            "failure_reasons": list(self.failure_reasons),
        }


@dataclass(frozen=True, slots=True)
class UpstoxLiveEventEvidence:
    sequence: int
    provider_timestamp: datetime | None
    local_receive_timestamp: datetime
    latency_seconds: Decimal | None
    instrument_key: str | None
    resolved_symbol: str | None
    event_type: str
    last_traded_price: Decimal | None
    volume: Decimal | None
    ohlc: Mapping[str, str]
    freshness_state: str
    decoder_outcome: str
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "provider_timestamp": (
                None
                if self.provider_timestamp is None
                else self.provider_timestamp.isoformat()
            ),
            "local_receive_timestamp": self.local_receive_timestamp.isoformat(),
            "latency_seconds": (
                None if self.latency_seconds is None else str(self.latency_seconds)
            ),
            "instrument_key": self.instrument_key,
            "resolved_symbol": self.resolved_symbol,
            "event_type": self.event_type,
            "last_traded_price": (
                None if self.last_traded_price is None else str(self.last_traded_price)
            ),
            "volume": None if self.volume is None else str(self.volume),
            "ohlc": dict(self.ohlc),
            "freshness_state": self.freshness_state,
            "decoder_outcome": self.decoder_outcome,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class UpstoxLiveProtocolEvidence:
    websocket_authorized: bool
    connection_opened: bool
    subscription_request_sent: bool
    subscription_acknowledged: bool
    first_event_received: bool
    heartbeat_received: bool
    malformed_event_count: int
    unknown_event_count: int
    duplicate_count: int
    out_of_order_count: int
    disconnect_reason: str
    clean_shutdown: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "websocket_authorized": self.websocket_authorized,
            "connection_opened": self.connection_opened,
            "subscription_request_sent": self.subscription_request_sent,
            "subscription_acknowledged": self.subscription_acknowledged,
            "first_event_received": self.first_event_received,
            "heartbeat_received": self.heartbeat_received,
            "malformed_event_count": self.malformed_event_count,
            "unknown_event_count": self.unknown_event_count,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "disconnect_reason": self.disconnect_reason,
            "clean_shutdown": self.clean_shutdown,
        }


@dataclass(frozen=True, slots=True)
class UpstoxLiveAcceptanceReport:
    run_id: str
    started_at: datetime
    ended_at: datetime
    provider_mode: UpstoxAcceptanceProviderMode
    preflight: UpstoxLiveAcceptancePreflight
    instrument: InstrumentSubscription | None
    events: tuple[UpstoxLiveEventEvidence, ...]
    protocol: UpstoxLiveProtocolEvidence
    one_minute_bars: tuple[LiveOHLCVBar, ...]
    five_minute_bars: tuple[LiveOHLCVBar, ...]
    order_api_call_count: int
    overall_classification: UpstoxLiveAcceptanceClassification
    failure_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "provider_mode": self.provider_mode.value,
            "preflight": self.preflight.as_dict(),
            "instrument": (
                None
                if self.instrument is None
                else {
                    "symbol": self.instrument.symbol,
                    "instrument_key": self.instrument.instrument_key,
                    "exchange": self.instrument.exchange,
                }
            ),
            "event_counts": {
                "accepted": len(self.events),
                "one_minute_completed_bars": len(self.one_minute_bars),
                "five_minute_completed_bars": len(self.five_minute_bars),
            },
            "protocol": self.protocol.as_dict(),
            "normalization_results": [event.as_dict() for event in self.events],
            "bar_results": {
                "one_minute": [_bar_dict(bar) for bar in self.one_minute_bars],
                "five_minute": [_bar_dict(bar) for bar in self.five_minute_bars],
            },
            "disconnect_outcome": {
                "reason": self.protocol.disconnect_reason,
                "clean_shutdown": self.protocol.clean_shutdown,
            },
            "order_api_call_count": self.order_api_call_count,
            "overall_classification": self.overall_classification.value,
            "failure_reasons": list(self.failure_reasons),
        }


@dataclass(slots=True)
class UpstoxLiveAcceptanceHarness:
    auth: UpstoxAcceptanceAuth = field(default_factory=UpstoxAuthService)
    resolver: UpstoxInstrumentResolver = field(default_factory=UpstoxInstrumentResolver)
    provider_factory: Any = UpstoxLiveMarketDataProvider.from_environment
    now: Any = lambda: datetime.now(UTC)

    def run(
        self,
        *,
        instrument_key: str,
        max_events: int,
        timeout_seconds: int,
    ) -> UpstoxLiveAcceptanceReport:
        return asyncio.run(
            self.run_async(
                instrument_key=instrument_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
            )
        )

    async def run_async(
        self,
        *,
        instrument_key: str,
        max_events: int,
        timeout_seconds: int,
    ) -> UpstoxLiveAcceptanceReport:
        started_at = self.now()
        run_id = _run_id(started_at, instrument_key)
        preflight = self.preflight(
            instrument_key=instrument_key,
            max_events=max_events,
            timeout_seconds=timeout_seconds,
        )
        if not preflight.passed:
            ended_at = self.now()
            return _preflight_failure_report(
                run_id=run_id,
                started_at=started_at,
                ended_at=ended_at,
                preflight=preflight,
            )
        assert preflight.resolved_symbol is not None
        assert preflight.resolved_exchange is not None
        instrument = InstrumentSubscription(
            symbol=preflight.resolved_symbol,
            instrument_key=instrument_key,
            exchange=preflight.resolved_exchange,
        )
        provider = self.provider_factory()
        return await self._run_provider(
            provider=provider,
            run_id=run_id,
            started_at=started_at,
            preflight=preflight,
            instrument=instrument,
            max_events=max_events,
            timeout_seconds=timeout_seconds,
        )

    def preflight(
        self,
        *,
        instrument_key: str,
        max_events: int,
        timeout_seconds: int,
    ) -> UpstoxLiveAcceptancePreflight:
        reasons: list[str] = []
        clean_key = instrument_key.strip()
        if max_events <= 0:
            reasons.append("max-events must be positive and finite.")
        if timeout_seconds <= 0:
            reasons.append("timeout-seconds must be positive and finite.")
        if _wildcard_instrument(clean_key):
            reasons.append("Wildcard or all-market subscriptions are not allowed.")
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=UpstoxLiveAcceptanceClassification.INSTRUMENT_NOT_RESOLVED,
                reasons=tuple(reasons),
            )
        metadata_available = self.auth.load_metadata() is not None
        local = self.auth.validate_token(remote=False)
        if local.status is UpstoxTokenStatus.TOKEN_MISSING:
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=UpstoxLiveAcceptanceClassification.TOKEN_UNAVAILABLE,
                reasons=("Upstox token is unavailable.",),
                token_metadata_available=metadata_available,
                remote_status=local.status.value,
            )
        if local.status is UpstoxTokenStatus.TOKEN_EXPIRED:
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=UpstoxLiveAcceptanceClassification.TOKEN_EXPIRED,
                reasons=("Upstox token is locally expired.",),
                token_metadata_available=metadata_available,
                token_locally_unexpired=False,
                remote_status=local.status.value,
            )
        remote = self.auth.validate_token(remote=True)
        if remote.status is not UpstoxTokenStatus.TOKEN_VALID:
            classification = (
                UpstoxLiveAcceptanceClassification.NO_ACTIVE_TRADING_SEGMENTS
                if "UDAPI100058" in remote.reason
                or "no active trading segments" in remote.reason.casefold()
                else UpstoxLiveAcceptanceClassification.TOKEN_REMOTE_VALIDATION_FAILED
            )
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=classification,
                reasons=(remote.reason,),
                token_metadata_available=metadata_available,
                remote_status=remote.status.value,
            )
        feed = self.auth.authorize_market_data_feed_v3()
        if not feed.authorized:
            classification = (
                UpstoxLiveAcceptanceClassification.NO_ACTIVE_TRADING_SEGMENTS
                if "UDAPI100058" in feed.reason
                or "no active trading segments" in feed.reason.casefold()
                else UpstoxLiveAcceptanceClassification.FEED_AUTHORIZATION_FAILED
            )
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=classification,
                reasons=(feed.reason,),
                token_metadata_available=metadata_available,
                remote_status=remote.status.value,
                feed_status=feed.status,
            )
        resolution = _resolve_acceptance_instrument(self.resolver, clean_key)
        if resolution.status is not InstrumentResolutionStatus.RESOLVED_EXACT:
            return _failed_preflight(
                instrument_key=clean_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
                classification=UpstoxLiveAcceptanceClassification.INSTRUMENT_NOT_RESOLVED,
                reasons=(f"Instrument resolution failed: {resolution.status.value}.",),
                token_metadata_available=metadata_available,
                remote_status=remote.status.value,
                feed_status=feed.status,
                resolution=resolution,
            )
        return UpstoxLiveAcceptancePreflight(
            configuration_available=True,
            token_metadata_available=metadata_available,
            token_locally_unexpired=True,
            remote_token_validation_status=remote.status.value,
            feed_authorization_status=feed.status,
            selected_instrument_key=clean_key,
            registry_resolution_status=resolution.status.value,
            resolved_symbol=resolution.requested_symbol,
            resolved_exchange=resolution.exchange,
            max_events=max_events,
            timeout_seconds=timeout_seconds,
            order_apis_disabled=True,
            passed=True,
        )

    async def _run_provider(
        self,
        *,
        provider: LiveAcceptanceProvider,
        run_id: str,
        started_at: datetime,
        preflight: UpstoxLiveAcceptancePreflight,
        instrument: InstrumentSubscription,
        max_events: int,
        timeout_seconds: int,
    ) -> UpstoxLiveAcceptanceReport:
        connection_opened = False
        subscription_sent = False
        clean_shutdown = False
        disconnect_reason = "not started"
        events: list[UpstoxLiveEventEvidence] = []
        one_minute = LiveBarBuilder(timeframe_minutes=1)
        five_minute = LiveBarBuilder(timeframe_minutes=5)
        quality = TickQualityEngine(subscriptions=(instrument,))
        previous_timestamp: datetime | None = None
        malformed = 0
        unknown = 0
        duplicate = 0
        out_of_order = 0
        try:
            await provider.connect()
            connection_opened = provider.status is LiveFeedStatus.CONNECTED
            await provider.subscribe((instrument,))
            subscription_sent = True
            deadline = self.now() + timedelta(seconds=timeout_seconds)
            iterator = provider.ticks()
            while len(events) < max_events:
                remaining = (deadline - self.now()).total_seconds()
                if remaining <= 0:
                    disconnect_reason = "timeout"
                    break
                try:
                    tick = await asyncio.wait_for(iterator.__anext__(), remaining)
                except StopAsyncIteration:
                    disconnect_reason = "provider stream ended"
                    break
                except TimeoutError:
                    disconnect_reason = "timeout"
                    break
                evidence, rejected = _event_evidence(
                    tick=tick,
                    sequence=len(events) + 1,
                    expected=instrument,
                    quality=quality,
                    received_at=self.now(),
                    previous_timestamp=previous_timestamp,
                )
                if evidence.decoder_outcome == "UNKNOWN_INSTRUMENT":
                    unknown += 1
                if evidence.decoder_outcome == "MALFORMED":
                    malformed += 1
                if "duplicate timestamp" in evidence.reasons:
                    duplicate += 1
                if "timestamp regression" in evidence.reasons:
                    out_of_order += 1
                if not rejected:
                    one_minute.update(tick)
                    five_minute.update(tick)
                    previous_timestamp = tick.observed_at
                events.append(evidence)
            if not disconnect_reason or disconnect_reason == "not started":
                disconnect_reason = "event bound reached"
        except KeyboardInterrupt:
            disconnect_reason = "interrupted"
        except RuntimeError as exc:
            disconnect_reason = f"connection failed: {exc}"
        except ValueError as exc:
            disconnect_reason = f"subscription failed: {exc}"
        finally:
            try:
                await provider.close()
                clean_shutdown = True
            except RuntimeError:
                clean_shutdown = False
        ended_at = self.now()
        protocol = UpstoxLiveProtocolEvidence(
            websocket_authorized=True,
            connection_opened=connection_opened,
            subscription_request_sent=subscription_sent,
            subscription_acknowledged=any(
                event.instrument_key == instrument.instrument_key for event in events
            ),
            first_event_received=bool(events),
            heartbeat_received=False,
            malformed_event_count=malformed,
            unknown_event_count=unknown,
            duplicate_count=duplicate,
            out_of_order_count=out_of_order,
            disconnect_reason=disconnect_reason,
            clean_shutdown=clean_shutdown,
        )
        cutoff = (
            ended_at
            if not events
            else max(event.local_receive_timestamp for event in events)
            + timedelta(minutes=5)
        )
        one_minute_bars = one_minute.completed_before(cutoff)
        five_minute_bars = five_minute.completed_before(cutoff)
        classification, failures = _classify_result(
            protocol=protocol,
            events=tuple(events),
            disconnect_reason=disconnect_reason,
        )
        return UpstoxLiveAcceptanceReport(
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at,
            provider_mode=UpstoxAcceptanceProviderMode.LIVE,
            preflight=preflight,
            instrument=instrument,
            events=tuple(events),
            protocol=protocol,
            one_minute_bars=one_minute_bars,
            five_minute_bars=five_minute_bars,
            order_api_call_count=0,
            overall_classification=classification,
            failure_reasons=failures,
        )


def render_upstox_live_acceptance(
    report: UpstoxLiveAcceptanceReport,
) -> tuple[str, ...]:
    lines = [
        "Upstox Bounded Live Acceptance",
        f"Run ID: {report.run_id}",
        f"Provider Mode: {report.provider_mode.value}",
        f"Instrument: {_instrument_text(report.instrument)}",
        f"Remote Token Validation: {report.preflight.remote_token_validation_status}",
        f"Feed V3 Authorization: {report.preflight.feed_authorization_status}",
        f"Registry Resolution: {report.preflight.registry_resolution_status}",
        f"Max Events: {report.preflight.max_events}",
        f"Timeout Seconds: {report.preflight.timeout_seconds}",
        f"Order APIs Disabled: {report.preflight.order_apis_disabled}",
        f"Connection Opened: {report.protocol.connection_opened}",
        f"Subscription Request Sent: {report.protocol.subscription_request_sent}",
        f"First Event Received: {report.protocol.first_event_received}",
        f"Events Accepted: {len(report.events)}",
        f"Malformed Events: {report.protocol.malformed_event_count}",
        f"Unknown Events: {report.protocol.unknown_event_count}",
        f"Duplicate Events: {report.protocol.duplicate_count}",
        f"Out-of-Order Events: {report.protocol.out_of_order_count}",
        f"1-Minute Completed Bars: {len(report.one_minute_bars)}",
        f"5-Minute Completed Bars: {len(report.five_minute_bars)}",
        f"Disconnect Reason: {report.protocol.disconnect_reason}",
        f"Clean Shutdown: {report.protocol.clean_shutdown}",
        f"Order API Calls: {report.order_api_call_count}",
        f"Overall Classification: {report.overall_classification.value}",
    ]
    if report.failure_reasons:
        lines.append("Failure Reasons:")
        lines.extend(f"- {reason}" for reason in report.failure_reasons)
    return tuple(lines)


def export_upstox_live_acceptance_json(
    report: UpstoxLiveAcceptanceReport,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _failed_preflight(
    *,
    instrument_key: str,
    max_events: int,
    timeout_seconds: int,
    classification: UpstoxLiveAcceptanceClassification,
    reasons: tuple[str, ...],
    token_metadata_available: bool = False,
    token_locally_unexpired: bool = False,
    remote_status: str = "NOT_REQUESTED",
    feed_status: str = "NOT_REQUESTED",
    resolution: UpstoxInstrumentResolution | None = None,
) -> UpstoxLiveAcceptancePreflight:
    return UpstoxLiveAcceptancePreflight(
        configuration_available=False,
        token_metadata_available=token_metadata_available,
        token_locally_unexpired=token_locally_unexpired,
        remote_token_validation_status=remote_status,
        feed_authorization_status=feed_status,
        selected_instrument_key=instrument_key,
        registry_resolution_status=(
            "NOT_REQUESTED" if resolution is None else resolution.status.value
        ),
        resolved_symbol=None if resolution is None else resolution.requested_symbol,
        resolved_exchange=None if resolution is None else resolution.exchange,
        max_events=max_events,
        timeout_seconds=timeout_seconds,
        order_apis_disabled=True,
        passed=False,
        failure_classification=classification,
        failure_reasons=reasons,
    )


def _preflight_failure_report(
    *,
    run_id: str,
    started_at: datetime,
    ended_at: datetime,
    preflight: UpstoxLiveAcceptancePreflight,
) -> UpstoxLiveAcceptanceReport:
    classification = (
        preflight.failure_classification
        or UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_FAILED
    )
    return UpstoxLiveAcceptanceReport(
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        provider_mode=UpstoxAcceptanceProviderMode.LIVE,
        preflight=preflight,
        instrument=None,
        events=(),
        protocol=UpstoxLiveProtocolEvidence(
            websocket_authorized=False,
            connection_opened=False,
            subscription_request_sent=False,
            subscription_acknowledged=False,
            first_event_received=False,
            heartbeat_received=False,
            malformed_event_count=0,
            unknown_event_count=0,
            duplicate_count=0,
            out_of_order_count=0,
            disconnect_reason="preflight failed",
            clean_shutdown=True,
        ),
        one_minute_bars=(),
        five_minute_bars=(),
        order_api_call_count=0,
        overall_classification=classification,
        failure_reasons=preflight.failure_reasons,
    )


def _resolve_acceptance_instrument(
    resolver: UpstoxInstrumentResolver,
    instrument_key: str,
) -> UpstoxInstrumentResolution:
    if hasattr(resolver, "resolve_instrument_key"):
        return resolver.resolve_instrument_key(instrument_key)
    return resolver.resolve(instrument_key)


def _wildcard_instrument(instrument_key: str) -> bool:
    cleaned = instrument_key.strip().upper()
    return cleaned in {"", "*", "ALL", "NSE_EQ|*", "BSE_EQ|*"} or "*" in cleaned


def _event_evidence(
    *,
    tick: LiveTick,
    sequence: int,
    expected: InstrumentSubscription,
    quality: TickQualityEngine,
    received_at: datetime,
    previous_timestamp: datetime | None,
) -> tuple[UpstoxLiveEventEvidence, bool]:
    reasons: list[str] = []
    instrument_matches = tick.instrument_key == expected.instrument_key
    if tick.instrument_key != expected.instrument_key:
        reasons.append("instrument mismatch")
    if tick.observed_at is None:
        reasons.append("missing provider timestamp")
    if tick.price <= Decimal("0"):
        reasons.append("missing non-fabricated price")
    assessment = quality.validate_tick(tick)
    reasons.extend(assessment.reasons)
    if previous_timestamp is not None and tick.observed_at < previous_timestamp:
        reasons.append("timestamp regression")
    rejected = (
        assessment.status is TickQualityStatus.INVALID
        or tick.instrument_key != expected.instrument_key
    )
    outcome = "ACCEPTED"
    if tick.instrument_key != expected.instrument_key:
        outcome = "UNKNOWN_INSTRUMENT"
    elif assessment.status is TickQualityStatus.INVALID:
        outcome = "MALFORMED"
    elif assessment.status is TickQualityStatus.SUSPECT:
        outcome = "ACCEPTED_WITH_WARNING"
    latency = Decimal(str((received_at - tick.observed_at).total_seconds())).quantize(
        Decimal("0.001")
    )
    freshness = "FRESH" if latency <= Decimal("15") else "STALE"
    return (
        UpstoxLiveEventEvidence(
            sequence=sequence,
            provider_timestamp=tick.observed_at,
            local_receive_timestamp=received_at,
            latency_seconds=latency,
            instrument_key=tick.instrument_key,
            resolved_symbol=expected.symbol if instrument_matches else None,
            event_type="tick",
            last_traded_price=tick.price,
            volume=tick.volume,
            ohlc={},
            freshness_state=freshness,
            decoder_outcome=outcome,
            reasons=tuple(dict.fromkeys(reasons)),
        ),
        rejected,
    )


def _classify_result(
    *,
    protocol: UpstoxLiveProtocolEvidence,
    events: tuple[UpstoxLiveEventEvidence, ...],
    disconnect_reason: str,
) -> tuple[UpstoxLiveAcceptanceClassification, tuple[str, ...]]:
    failures: list[str] = []
    if disconnect_reason.startswith("connection failed"):
        return (
            UpstoxLiveAcceptanceClassification.LIVE_CONNECTION_FAILED,
            (disconnect_reason,),
        )
    if disconnect_reason.startswith("subscription failed"):
        return (
            UpstoxLiveAcceptanceClassification.SUBSCRIPTION_FAILED,
            (disconnect_reason,),
        )
    if disconnect_reason == "interrupted":
        return (
            UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_INTERRUPTED,
            ("Acceptance run was interrupted and cleaned up.",),
        )
    valid_events = tuple(
        event
        for event in events
        if event.decoder_outcome
        in {
            "ACCEPTED",
            "ACCEPTED_WITH_WARNING",
        }
    )
    if not valid_events:
        if protocol.connection_opened and protocol.subscription_request_sent:
            return (
                UpstoxLiveAcceptanceClassification.LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS,
                ("No market data arrived during the bounded run.",),
            )
        return (
            UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_TIMEOUT,
            ("No valid live event was decoded.",),
        )
    if not protocol.clean_shutdown:
        failures.append("Connection did not close cleanly.")
    if protocol.unknown_event_count:
        failures.append("Unknown instrument events were observed.")
    if failures:
        return (
            UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_FAILED,
            tuple(failures),
        )
    return UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_PASS, ()


def _run_id(started_at: datetime, instrument_key: str) -> str:
    safe_key = instrument_key.replace("|", "_").replace(" ", "_")
    return f"upstox-live-{started_at.strftime('%Y%m%dT%H%M%S')}-{safe_key}"


def _bar_dict(bar: LiveOHLCVBar) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "started_at": bar.started_at.isoformat(),
        "timeframe_minutes": bar.timeframe_minutes,
        "open": str(bar.open_price),
        "high": str(bar.high_price),
        "low": str(bar.low_price),
        "close": str(bar.close_price),
        "volume": str(bar.volume),
        "vwap": None if bar.vwap is None else str(bar.vwap),
    }


def _instrument_text(instrument: InstrumentSubscription | None) -> str:
    if instrument is None:
        return "unavailable"
    return f"{instrument.symbol} ({instrument.exchange}, {instrument.instrument_key})"


__all__ = [
    "LiveAcceptanceProvider",
    "UpstoxAcceptanceProviderMode",
    "UpstoxLiveAcceptanceClassification",
    "UpstoxLiveAcceptanceHarness",
    "UpstoxLiveAcceptancePreflight",
    "UpstoxLiveAcceptanceReport",
    "UpstoxLiveEventEvidence",
    "UpstoxLiveProtocolEvidence",
    "export_upstox_live_acceptance_json",
    "render_upstox_live_acceptance",
]
