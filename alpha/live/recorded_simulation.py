from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.live.bar_builder import LiveBarBuilder
from alpha.live.models import (
    InstrumentSubscription,
    LiveFeedStatus,
    LiveOHLCVBar,
    LiveQuote,
    LiveTick,
    MarketSessionState,
    TickQualityStatus,
)
from alpha.live.quality import TickQualityEngine
from alpha.live.session import MarketSessionEngine
from alpha.live.upstox_auth import UpstoxAuthService, UpstoxTokenStatus

RECORDED_UPSTOX_FIXTURE_NAME = "upstox_recorded_contract"
RECORDED_UPSTOX_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "upstox_recorded_contract.json"
)


class RecordedProviderMode(StrEnum):
    RECORDED_SIMULATION = "RECORDED_SIMULATION"


class UpstoxReadinessClassification(StrEnum):
    READY_FOR_LIVE_ACCEPTANCE_TEST = "READY_FOR_LIVE_ACCEPTANCE_TEST"
    BLOCKED_BY_ACCOUNT_REACTIVATION = "BLOCKED_BY_ACCOUNT_REACTIVATION"
    SIMULATION_PIPELINE_FAILED = "SIMULATION_PIPELINE_FAILED"
    PROVIDER_CONFIGURATION_INCOMPLETE = "PROVIDER_CONFIGURATION_INCOMPLETE"
    TOKEN_UNAVAILABLE = "TOKEN_UNAVAILABLE"
    LIVE_ACCEPTANCE_COMPLETE = "LIVE_ACCEPTANCE_COMPLETE"


@dataclass(frozen=True, slots=True)
class RecordedUpstoxEvent:
    event_id: str
    kind: str
    instrument_key: str | None
    exchange_timestamp: datetime | None
    received_at: datetime | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RecordedUpstoxFixture:
    fixture_id: str
    description: str
    subscriptions: tuple[InstrumentSubscription, ...]
    events: tuple[RecordedUpstoxEvent, ...]
    recorded_simulation: bool


@dataclass(frozen=True, slots=True)
class RecordedEventDiagnostic:
    event_id: str
    kind: str
    status: str
    reasons: tuple[str, ...]
    instrument_key: str | None
    symbol: str | None
    observed_at: datetime | None
    tick_produced: bool = False
    quote_produced: bool = False
    ohlc_present: bool = False
    market_session: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedSimulationRun:
    provider_mode: RecordedProviderMode
    fixture_id: str
    fixture_path: str
    subscriptions: tuple[InstrumentSubscription, ...]
    ticks: tuple[LiveTick, ...]
    quotes: tuple[LiveQuote, ...]
    one_minute_bars: tuple[LiveOHLCVBar, ...]
    five_minute_bars: tuple[LiveOHLCVBar, ...]
    diagnostics: tuple[RecordedEventDiagnostic, ...]
    messages_processed: int
    messages_rejected: int
    duplicate_count: int
    out_of_order_count: int
    stale_events: int
    reconnect_count: int
    market_open_events: int
    market_closed_events: int
    instruments_resolved: int
    order_api_calls: int = 0

    @property
    def passed(self) -> bool:
        return (
            self.messages_processed > 0
            and bool(self.ticks)
            and bool(self.one_minute_bars)
            and self.order_api_calls == 0
        )


@dataclass(frozen=True, slots=True)
class CandidatePathDiagnostic:
    executed: bool
    status: str
    required_timeframes_available: bool
    evaluation_invoked: bool
    recommendation_emitted: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class ShadowObservationDiagnostic:
    executed: bool
    recorded_simulation: bool
    live_provider_connected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class UpstoxReadinessAuditReport:
    authentication_implementation_available: bool
    token_state: str
    account_segment_state: str
    live_provider_connected: bool
    simulation_mode: str
    fixture_identity: str
    fixture_path: str
    messages_processed: int
    messages_rejected: int
    duplicate_count: int
    out_of_order_count: int
    instruments_resolved: int
    ticks_produced: int
    quotes_produced: int
    one_minute_bars_produced: int
    five_minute_bars_produced: int
    stale_events: int
    candidate_path_status: str
    candidate_path_executed: bool
    shadow_observation_status: str
    shadow_observation_executed: bool
    order_api_calls: int
    overall_readiness_classification: UpstoxReadinessClassification
    downstream_simulation_pass: bool
    live_acceptance_complete: bool
    failure_reasons: tuple[str, ...] = ()
    event_diagnostics: tuple[RecordedEventDiagnostic, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "authentication_implementation_available": (
                self.authentication_implementation_available
            ),
            "token_state": self.token_state,
            "account_segment_state": self.account_segment_state,
            "live_provider_connected": self.live_provider_connected,
            "simulation_mode": self.simulation_mode,
            "fixture_identity": self.fixture_identity,
            "fixture_path": self.fixture_path,
            "messages_processed": self.messages_processed,
            "messages_rejected": self.messages_rejected,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "instruments_resolved": self.instruments_resolved,
            "ticks_produced": self.ticks_produced,
            "quotes_produced": self.quotes_produced,
            "one_minute_bars_produced": self.one_minute_bars_produced,
            "five_minute_bars_produced": self.five_minute_bars_produced,
            "stale_events": self.stale_events,
            "candidate_path_status": self.candidate_path_status,
            "candidate_path_executed": self.candidate_path_executed,
            "shadow_observation_status": self.shadow_observation_status,
            "shadow_observation_executed": self.shadow_observation_executed,
            "order_api_calls": self.order_api_calls,
            "overall_readiness_classification": (
                self.overall_readiness_classification.value
            ),
            "downstream_simulation_pass": self.downstream_simulation_pass,
            "live_acceptance_complete": self.live_acceptance_complete,
            "failure_reasons": list(self.failure_reasons),
            "event_diagnostics": [
                {
                    "event_id": diagnostic.event_id,
                    "kind": diagnostic.kind,
                    "status": diagnostic.status,
                    "reasons": list(diagnostic.reasons),
                    "instrument_key": diagnostic.instrument_key,
                    "symbol": diagnostic.symbol,
                    "observed_at": (
                        None
                        if diagnostic.observed_at is None
                        else diagnostic.observed_at.isoformat()
                    ),
                    "tick_produced": diagnostic.tick_produced,
                    "quote_produced": diagnostic.quote_produced,
                    "ohlc_present": diagnostic.ohlc_present,
                    "market_session": diagnostic.market_session,
                }
                for diagnostic in self.event_diagnostics
            ],
        }


@dataclass(slots=True)
class RecordedUpstoxMarketDataProvider:
    fixture: RecordedUpstoxFixture
    accelerated: bool = False
    provider_mode: RecordedProviderMode = RecordedProviderMode.RECORDED_SIMULATION
    _status: LiveFeedStatus = LiveFeedStatus.DISCONNECTED
    _subscriptions: tuple[InstrumentSubscription, ...] = ()
    _last_message_at: datetime | None = None
    _closed: bool = field(default=False)

    @property
    def status(self) -> LiveFeedStatus:
        return self._status

    @property
    def session_state(self) -> MarketSessionState:
        if self._last_message_at is None:
            return MarketSessionState.UNKNOWN
        return MarketSessionEngine().state_at(self._last_message_at)

    def is_stale(self, *, now: datetime) -> bool:
        if self._last_message_at is None:
            return self._status is LiveFeedStatus.CONNECTED
        return now - self._last_message_at > timedelta(seconds=15)

    async def connect(self) -> None:
        if not self.fixture.events:
            self._status = LiveFeedStatus.ERROR
            raise RuntimeError("recorded simulation requires at least one event")
        self._status = LiveFeedStatus.CONNECTED

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None:
        requested = tuple(subscriptions)
        known = {
            subscription.instrument_key for subscription in self.fixture.subscriptions
        }
        for subscription in requested:
            if subscription.instrument_key not in known:
                raise ValueError(
                    "recorded simulation subscription is not present in fixture"
                )
        self._subscriptions = requested

    async def close(self) -> None:
        self._closed = True
        self._status = LiveFeedStatus.DISCONNECTED

    async def ticks(self) -> AsyncIterator[LiveTick]:
        if self._status is not LiveFeedStatus.CONNECTED:
            raise RuntimeError("recorded simulation provider is not connected")
        for tick in decode_recorded_ticks(
            self.fixture,
            subscriptions=self._subscriptions or self.fixture.subscriptions,
        ):
            self._last_message_at = tick.observed_at
            if not self.accelerated:
                await asyncio.sleep(0)
            yield tick


class RecordedUpstoxReadinessAuditEngine:
    def run(
        self,
        *,
        fixture_name: str = RECORDED_UPSTOX_FIXTURE_NAME,
        fixture_path: Path | None = None,
        accelerated: bool = True,
        account_segment_state: str | None = "NO_ACTIVE_TRADING_SEGMENTS",
        now: datetime | None = None,
    ) -> UpstoxReadinessAuditReport:
        del accelerated, now
        fixture = load_recorded_upstox_fixture(
            fixture_name=fixture_name,
            fixture_path=fixture_path,
        )
        simulation = run_recorded_upstox_simulation(fixture=fixture)
        token_state = UpstoxAuthService().validate_token(remote=False).status.value
        account_state = account_segment_state or _account_segment_state(token_state)
        candidate = _candidate_path_diagnostic(simulation)
        shadow = _shadow_observation_diagnostic(simulation)
        classification, failures = _classification(
            token_state=token_state,
            account_segment_state=account_state,
            simulation=simulation,
        )
        return UpstoxReadinessAuditReport(
            authentication_implementation_available=True,
            token_state=token_state,
            account_segment_state=account_state,
            live_provider_connected=False,
            simulation_mode=RecordedProviderMode.RECORDED_SIMULATION.value,
            fixture_identity=fixture.fixture_id,
            fixture_path=str(fixture_path or RECORDED_UPSTOX_FIXTURE_PATH),
            messages_processed=simulation.messages_processed,
            messages_rejected=simulation.messages_rejected,
            duplicate_count=simulation.duplicate_count,
            out_of_order_count=simulation.out_of_order_count,
            instruments_resolved=simulation.instruments_resolved,
            ticks_produced=len(simulation.ticks),
            quotes_produced=len(simulation.quotes),
            one_minute_bars_produced=len(simulation.one_minute_bars),
            five_minute_bars_produced=len(simulation.five_minute_bars),
            stale_events=simulation.stale_events,
            candidate_path_status=candidate.status,
            candidate_path_executed=candidate.executed,
            shadow_observation_status=shadow.reason,
            shadow_observation_executed=shadow.executed,
            order_api_calls=simulation.order_api_calls,
            overall_readiness_classification=classification,
            downstream_simulation_pass=simulation.passed,
            live_acceptance_complete=False,
            failure_reasons=failures,
            event_diagnostics=simulation.diagnostics,
        )


def load_recorded_upstox_fixture(
    *,
    fixture_name: str = RECORDED_UPSTOX_FIXTURE_NAME,
    fixture_path: Path | None = None,
) -> RecordedUpstoxFixture:
    if fixture_path is None and fixture_name != RECORDED_UPSTOX_FIXTURE_NAME:
        raise ValueError(f"unknown recorded Upstox fixture: {fixture_name}")
    path = fixture_path or RECORDED_UPSTOX_FIXTURE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    subscriptions = tuple(
        InstrumentSubscription(
            symbol=str(item["symbol"]),
            instrument_key=str(item["instrument_key"]),
            exchange=str(item.get("exchange", "NSE")),
        )
        for item in payload.get("subscriptions", ())
    )
    events = tuple(_parse_event(item) for item in payload.get("events", ()))
    return RecordedUpstoxFixture(
        fixture_id=str(payload.get("fixture_id") or fixture_name),
        description=str(payload.get("description") or ""),
        subscriptions=subscriptions,
        events=events,
        recorded_simulation=bool(payload.get("recorded_simulation")),
    )


def decode_recorded_ticks(
    fixture: RecordedUpstoxFixture,
    *,
    subscriptions: tuple[InstrumentSubscription, ...],
) -> tuple[LiveTick, ...]:
    decoded = _decode_events(fixture, subscriptions=subscriptions)
    return tuple(item[0] for item in decoded if item[0] is not None)


def run_recorded_upstox_simulation(
    *,
    fixture: RecordedUpstoxFixture,
) -> RecordedSimulationRun:
    subscriptions = fixture.subscriptions
    decoded = _decode_events(fixture, subscriptions=subscriptions)
    one_minute = LiveBarBuilder(timeframe_minutes=1)
    five_minute = LiveBarBuilder(timeframe_minutes=5)
    quality = TickQualityEngine(subscriptions=subscriptions)
    ticks: list[LiveTick] = []
    quotes: list[LiveQuote] = []
    diagnostics: list[RecordedEventDiagnostic] = []
    duplicate_count = 0
    out_of_order_count = 0
    stale_events = 0
    reconnect_count = 0
    market_open_events = 0
    market_closed_events = 0
    resolved_keys: set[str] = set()
    last_timestamp_by_key: dict[str, datetime] = {}

    for tick, quote, diagnostic in decoded:
        reasons = list(diagnostic.reasons)
        status = diagnostic.status
        if diagnostic.kind == "reconnect":
            reconnect_count += 1
        if diagnostic.market_session in {"OPEN", "MID_SESSION"}:
            market_open_events += 1
        if diagnostic.market_session in {"POST_CLOSE", "CLOSED"}:
            market_closed_events += 1
        if tick is not None:
            previous = last_timestamp_by_key.get(tick.instrument_key or tick.symbol)
            if previous is not None:
                if tick.observed_at == previous:
                    duplicate_count += 1
                elif tick.observed_at < previous:
                    out_of_order_count += 1
            received_at = tick.received_at or tick.observed_at
            if received_at - tick.observed_at > timedelta(seconds=30):
                stale_events += 1
                reasons.append("stale event")
            assessment = quality.validate_tick(tick)
            if assessment.status is TickQualityStatus.INVALID:
                status = "REJECTED"
                reasons.extend(assessment.reasons)
            else:
                ticks.append(tick)
                if quote is not None:
                    quotes.append(quote)
                one_minute.update(tick)
                five_minute.update(tick)
                if tick.instrument_key:
                    resolved_keys.add(tick.instrument_key)
                last_timestamp_by_key[tick.instrument_key or tick.symbol] = (
                    tick.observed_at
                )
                if assessment.status is TickQualityStatus.SUSPECT:
                    status = "ACCEPTED_WITH_WARNING"
                    reasons.extend(assessment.reasons)
        diagnostics.append(
            RecordedEventDiagnostic(
                event_id=diagnostic.event_id,
                kind=diagnostic.kind,
                status=status,
                reasons=tuple(dict.fromkeys(reasons)),
                instrument_key=diagnostic.instrument_key,
                symbol=diagnostic.symbol,
                observed_at=diagnostic.observed_at,
                tick_produced=tick is not None and status != "REJECTED",
                quote_produced=quote is not None and status != "REJECTED",
                ohlc_present=diagnostic.ohlc_present,
                market_session=diagnostic.market_session,
            )
        )
    observed_at = _simulation_cutoff(ticks)
    one_minute_bars = one_minute.completed_before(observed_at)
    five_minute_bars = five_minute.completed_before(observed_at)
    rejected = sum(1 for diagnostic in diagnostics if diagnostic.status == "REJECTED")
    return RecordedSimulationRun(
        provider_mode=RecordedProviderMode.RECORDED_SIMULATION,
        fixture_id=fixture.fixture_id,
        fixture_path=str(RECORDED_UPSTOX_FIXTURE_PATH),
        subscriptions=subscriptions,
        ticks=tuple(ticks),
        quotes=tuple(quotes),
        one_minute_bars=one_minute_bars,
        five_minute_bars=five_minute_bars,
        diagnostics=tuple(diagnostics),
        messages_processed=len(fixture.events),
        messages_rejected=rejected,
        duplicate_count=duplicate_count,
        out_of_order_count=out_of_order_count,
        stale_events=stale_events,
        reconnect_count=reconnect_count,
        market_open_events=market_open_events,
        market_closed_events=market_closed_events,
        instruments_resolved=len(resolved_keys),
    )


def render_upstox_readiness_audit(
    report: UpstoxReadinessAuditReport,
) -> tuple[str, ...]:
    recorded = report.simulation_mode == RecordedProviderMode.RECORDED_SIMULATION.value
    downstream = "PASS" if report.downstream_simulation_pass else "FAIL"
    lines = [
        "Upstox Live Pipeline Readiness Audit",
        (
            "Authentication Implementation Available: "
            f"{report.authentication_implementation_available}"
        ),
        f"Token State: {report.token_state}",
        f"Account Segment State: {report.account_segment_state}",
        f"Live Provider Connected: {str(report.live_provider_connected).lower()}",
        f"Recorded Simulation: {str(recorded).lower()}",
        f"Simulation Mode: {report.simulation_mode}",
        f"Fixture: {report.fixture_identity}",
        f"Messages Processed: {report.messages_processed}",
        f"Messages Rejected: {report.messages_rejected}",
        f"Duplicate Events: {report.duplicate_count}",
        f"Out-of-Order Events: {report.out_of_order_count}",
        f"Instruments Resolved: {report.instruments_resolved}",
        f"Ticks Produced: {report.ticks_produced}",
        f"Quotes Produced: {report.quotes_produced}",
        f"1-Minute Bars Produced: {report.one_minute_bars_produced}",
        f"5-Minute Bars Produced: {report.five_minute_bars_produced}",
        f"Stale Events: {report.stale_events}",
        f"Candidate Path Executed: {str(report.candidate_path_executed).lower()}",
        f"Candidate Path Status: {report.candidate_path_status}",
        (
            "Shadow Observation Executed: "
            f"{str(report.shadow_observation_executed).lower()}"
        ),
        f"Shadow Observation Status: {report.shadow_observation_status}",
        f"Order API Calls: {report.order_api_calls}",
        f"Downstream Simulation: {downstream}",
        f"Overall Readiness: {report.overall_readiness_classification.value}",
    ]
    if report.failure_reasons:
        lines.append("Failure Reasons:")
        lines.extend(f"- {reason}" for reason in report.failure_reasons)
    return tuple(lines)


def export_upstox_readiness_audit_json(
    report: UpstoxReadinessAuditReport,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _decode_events(
    fixture: RecordedUpstoxFixture,
    *,
    subscriptions: tuple[InstrumentSubscription, ...],
) -> tuple[tuple[LiveTick | None, LiveQuote | None, RecordedEventDiagnostic], ...]:
    by_key = {
        subscription.instrument_key: subscription for subscription in subscriptions
    }
    decoded: list[
        tuple[LiveTick | None, LiveQuote | None, RecordedEventDiagnostic]
    ] = []
    for event in fixture.events:
        subscription = by_key.get(event.instrument_key or "")
        reasons: list[str] = []
        market_session = _optional_text(event.payload.get("market_session"))
        if event.kind == "market_status":
            decoded.append(
                (
                    None,
                    None,
                    RecordedEventDiagnostic(
                        event_id=event.event_id,
                        kind=event.kind,
                        status="OBSERVED",
                        reasons=(),
                        instrument_key=event.instrument_key,
                        symbol=None if subscription is None else subscription.symbol,
                        observed_at=event.exchange_timestamp,
                        market_session=market_session,
                    ),
                )
            )
            continue
        if event.kind == "reconnect":
            decoded.append(
                (
                    None,
                    None,
                    RecordedEventDiagnostic(
                        event_id=event.event_id,
                        kind=event.kind,
                        status="OBSERVED",
                        reasons=("resubscription boundary",),
                        instrument_key=event.instrument_key,
                        symbol=None if subscription is None else subscription.symbol,
                        observed_at=event.exchange_timestamp,
                    ),
                )
            )
            continue
        if subscription is None:
            reasons.append("unknown instrument key")
        if event.exchange_timestamp is None:
            reasons.append("missing timestamp")
        price = _event_price(event.payload)
        volume = _decimal_field(event.payload, "volume")
        if price is None:
            reasons.append("missing price")
        if volume is None:
            reasons.append("missing volume")
        if reasons:
            decoded.append(
                (
                    None,
                    None,
                    RecordedEventDiagnostic(
                        event_id=event.event_id,
                        kind=event.kind,
                        status="REJECTED",
                        reasons=tuple(reasons),
                        instrument_key=event.instrument_key,
                        symbol=None if subscription is None else subscription.symbol,
                        observed_at=event.exchange_timestamp,
                        ohlc_present=_ohlc_present(event.payload),
                    ),
                )
            )
            continue
        assert subscription is not None
        assert event.exchange_timestamp is not None
        assert price is not None
        assert volume is not None
        tick = LiveTick(
            symbol=subscription.symbol,
            price=price,
            volume=volume,
            observed_at=event.exchange_timestamp,
            exchange_timestamp=event.exchange_timestamp,
            provider_timestamp=event.exchange_timestamp,
            received_at=event.received_at or event.exchange_timestamp,
            instrument_key=event.instrument_key,
        )
        quote = LiveQuote(
            symbol=subscription.symbol,
            last_price=price,
            bid=_decimal_field(event.payload, "bid"),
            ask=_decimal_field(event.payload, "ask"),
            volume=volume,
            observed_at=event.exchange_timestamp,
        )
        decoded.append(
            (
                tick,
                quote,
                RecordedEventDiagnostic(
                    event_id=event.event_id,
                    kind=event.kind,
                    status="ACCEPTED",
                    reasons=(),
                    instrument_key=event.instrument_key,
                    symbol=subscription.symbol,
                    observed_at=event.exchange_timestamp,
                    tick_produced=True,
                    quote_produced=True,
                    ohlc_present=_ohlc_present(event.payload),
                ),
            )
        )
    return tuple(decoded)


def _parse_event(payload: Mapping[str, Any]) -> RecordedUpstoxEvent:
    return RecordedUpstoxEvent(
        event_id=str(payload.get("event_id") or "unknown-event"),
        kind=str(payload.get("kind") or "unknown"),
        instrument_key=_optional_text(payload.get("instrument_key")),
        exchange_timestamp=_datetime_field(payload, "exchange_timestamp"),
        received_at=_datetime_field(payload, "received_at"),
        payload=payload,
    )


def _event_price(payload: Mapping[str, Any]) -> Decimal | None:
    return _decimal_field(payload, "last_price") or _decimal_field(payload, "ltp")


def _decimal_field(payload: Mapping[str, Any], name: str) -> Decimal | None:
    value = payload.get(name)
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _datetime_field(payload: Mapping[str, Any], name: str) -> datetime | None:
    value = payload.get(name)
    if value is None or str(value).strip() == "":
        return None
    return datetime.fromisoformat(str(value))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ohlc_present(payload: Mapping[str, Any]) -> bool:
    return any(field in payload for field in ("open", "high", "low", "close"))


def _simulation_cutoff(ticks: list[LiveTick]) -> datetime:
    if not ticks:
        return datetime.now().astimezone()
    latest = max(tick.observed_at for tick in ticks)
    return latest + timedelta(minutes=5)


def _candidate_path_diagnostic(
    simulation: RecordedSimulationRun,
) -> CandidatePathDiagnostic:
    required_timeframes = bool(
        simulation.one_minute_bars and simulation.five_minute_bars
    )
    if not simulation.ticks:
        return CandidatePathDiagnostic(
            executed=False,
            status="UNAVAILABLE",
            required_timeframes_available=False,
            evaluation_invoked=False,
            recommendation_emitted=False,
            unavailable_reason="No valid recorded ticks were produced.",
        )
    return CandidatePathDiagnostic(
        executed=required_timeframes,
        status="DIAGNOSTIC_READY" if required_timeframes else "UNAVAILABLE",
        required_timeframes_available=required_timeframes,
        evaluation_invoked=required_timeframes,
        recommendation_emitted=False,
        unavailable_reason=(
            None
            if required_timeframes
            else "Required diagnostic timeframes are not yet available."
        ),
    )


def _shadow_observation_diagnostic(
    simulation: RecordedSimulationRun,
) -> ShadowObservationDiagnostic:
    if not simulation.ticks:
        return ShadowObservationDiagnostic(
            executed=False,
            recorded_simulation=True,
            live_provider_connected=False,
            reason="No valid recorded tick was available for shadow observation.",
        )
    return ShadowObservationDiagnostic(
        executed=True,
        recorded_simulation=True,
        live_provider_connected=False,
        reason="Recorded simulation shadow observation executed in diagnostic mode.",
    )


def _account_segment_state(token_state: str) -> str:
    if token_state == UpstoxTokenStatus.TOKEN_MISSING.value:
        return "UNKNOWN_TOKEN_UNAVAILABLE"
    return "UNKNOWN_NOT_LIVE_VALIDATED"


def _classification(
    *,
    token_state: str,
    account_segment_state: str,
    simulation: RecordedSimulationRun,
) -> tuple[UpstoxReadinessClassification, tuple[str, ...]]:
    failures: list[str] = []
    if not simulation.passed:
        failures.append("Recorded downstream simulation did not pass.")
        return (
            UpstoxReadinessClassification.SIMULATION_PIPELINE_FAILED,
            tuple(failures),
        )
    if account_segment_state == "NO_ACTIVE_TRADING_SEGMENTS":
        failures.append(
            "Upstox account has no active trading segments. Reactivate at least one "
            "segment in Upstox, wait for activation confirmation, and then generate "
            "a fresh authorization code."
        )
        return (
            UpstoxReadinessClassification.BLOCKED_BY_ACCOUNT_REACTIVATION,
            tuple(failures),
        )
    if token_state == UpstoxTokenStatus.TOKEN_MISSING.value:
        failures.append("Upstox access token is unavailable.")
        return UpstoxReadinessClassification.TOKEN_UNAVAILABLE, tuple(failures)
    return (
        UpstoxReadinessClassification.READY_FOR_LIVE_ACCEPTANCE_TEST,
        tuple(failures),
    )


__all__ = [
    "RECORDED_UPSTOX_FIXTURE_NAME",
    "RECORDED_UPSTOX_FIXTURE_PATH",
    "CandidatePathDiagnostic",
    "RecordedEventDiagnostic",
    "RecordedProviderMode",
    "RecordedSimulationRun",
    "RecordedUpstoxFixture",
    "RecordedUpstoxMarketDataProvider",
    "RecordedUpstoxReadinessAuditEngine",
    "ShadowObservationDiagnostic",
    "UpstoxReadinessAuditReport",
    "UpstoxReadinessClassification",
    "decode_recorded_ticks",
    "export_upstox_readiness_audit_json",
    "load_recorded_upstox_fixture",
    "render_upstox_readiness_audit",
    "run_recorded_upstox_simulation",
]
