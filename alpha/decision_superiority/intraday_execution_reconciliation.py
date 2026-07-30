"""Exact Upstox identity resolution and daily/intraday source reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionError,
    IntradayExecutionPolicy,
)

PRICE_TOLERANCE = 0.011
VOLUME_TOLERANCE = 0


class IdentityResolutionState(StrEnum):
    """Fail-closed identity resolution states for one governed security."""

    RESOLVED = "RESOLVED_EXACT_ISIN_NSE_EQUITY"
    GOVERNED_IDENTITY_INVALID = "GOVERNED_IDENTITY_INVALID"
    SOURCE_RECORD_MISSING = "SOURCE_RECORD_MISSING"
    SOURCE_RECORD_AMBIGUOUS = "SOURCE_RECORD_AMBIGUOUS"
    SOURCE_RECORD_CONTRACT_INVALID = "SOURCE_RECORD_CONTRACT_INVALID"


class DailyReconciliationState(StrEnum):
    """Daily versus intraday reconciliation states."""

    RECONCILED = "RECONCILED_RAW_DAILY_TO_INTRADAY"
    EMPTY_INTRADAY_SESSION = "EMPTY_INTRADAY_SESSION"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INSTRUMENT_KEY_MISMATCH = "INSTRUMENT_KEY_MISMATCH"
    SESSION_DATE_MISMATCH = "SESSION_DATE_MISMATCH"
    INCOMPLETE_REGULAR_SESSION = "INCOMPLETE_REGULAR_SESSION"
    DAILY_PRICE_BASIS_INVALID = "DAILY_PRICE_BASIS_INVALID"
    DAILY_OHLC_MISMATCH = "DAILY_OHLC_MISMATCH"
    DAILY_VOLUME_MISMATCH = "DAILY_VOLUME_MISMATCH"


@dataclass(frozen=True, slots=True)
class UpstoxInstrumentRecord:
    """Minimal immutable Upstox cash-market identity record."""

    name: str
    exchange: str
    segment: str
    isin: str
    instrument_key: str
    exchange_token: str
    trading_symbol: str
    instrument_type: str


@dataclass(frozen=True, slots=True)
class InstrumentResolution:
    """Exact governed identity to Upstox instrument resolution evidence."""

    governed_identity: str
    governed_isin: str | None
    state: IdentityResolutionState
    instrument: UpstoxInstrumentRecord | None
    source_sha256: str
    resolved_at: datetime
    blocker: str | None = None
    source_instrument_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DailyCandleReference:
    """Governed raw daily candle used only to certify the broker source."""

    governed_identity: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    price_basis: str
    source_sha256: str

    def __post_init__(self) -> None:
        if self.price_basis != "RAW":
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_MUST_BE_RAW")
        if len(self.source_sha256) != 64:
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_HASH_INVALID")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_PRICE_INVALID")
        if self.low > min(self.open, self.close):
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_OHLC_INVALID")
        if self.high < max(self.open, self.close) or self.low > self.high:
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_OHLC_INVALID")
        if self.volume < 0:
            raise IntradayExecutionError("DSI013_DAILY_REFERENCE_VOLUME_INVALID")


@dataclass(frozen=True, slots=True)
class AggregatedIntradaySession:
    """One instrument/session aggregate derived only from admitted bars."""

    governed_identity: str
    instrument_key: str
    session_date: date
    bar_count: int
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class DailyReconciliationResult:
    """Deterministic raw daily versus intraday reconciliation evidence."""

    state: DailyReconciliationState
    passed: bool
    blockers: tuple[str, ...]
    aggregate: AggregatedIntradaySession | None
    metric_rows: tuple[dict[str, Any], ...]


def instrument_source_sha256(payload: object) -> str:
    """Hash one normalized instrument-source payload deterministically."""

    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_upstox_instrument_payload(
    payload: object,
) -> tuple[UpstoxInstrumentRecord, ...]:
    """Parse either a BOD instrument array or Instrument Search response."""

    records_value: object
    if isinstance(payload, Mapping):
        if payload.get("status") != "success":
            raise IntradayExecutionError("DSI013_INSTRUMENT_RESPONSE_NOT_SUCCESS")
        records_value = payload.get("data")
    else:
        records_value = payload
    if not isinstance(records_value, list):
        raise IntradayExecutionError("DSI013_INSTRUMENT_RESPONSE_SCHEMA_INVALID")

    records: list[UpstoxInstrumentRecord] = []
    for index, value in enumerate(records_value):
        if not isinstance(value, Mapping):
            raise IntradayExecutionError(
                f"DSI013_INSTRUMENT_RECORD_SCHEMA_INVALID:{index}"
            )
        try:
            record = UpstoxInstrumentRecord(
                name=str(value.get("name", "")),
                exchange=str(value["exchange"]),
                segment=str(value["segment"]),
                isin=str(value["isin"]),
                instrument_key=str(value["instrument_key"]),
                exchange_token=str(value.get("exchange_token", "")),
                trading_symbol=str(value.get("trading_symbol", "")),
                instrument_type=str(value["instrument_type"]),
            )
        except KeyError as exc:
            raise IntradayExecutionError(
                f"DSI013_INSTRUMENT_RECORD_FIELD_MISSING:{index}:{exc.args[0]}"
            ) from exc
        records.append(record)
    return tuple(records)


def resolve_upstox_nse_equity(
    governed_identity: str,
    records: Sequence[UpstoxInstrumentRecord],
    *,
    source_sha256: str,
    resolved_at: datetime | None = None,
) -> InstrumentResolution:
    """Resolve an exact governed NSE ISIN to one canonical cash-market key."""

    timestamp = (resolved_at or datetime.now(UTC)).astimezone(UTC)
    isin = _governed_isin(governed_identity)
    if isin is None:
        return InstrumentResolution(
            governed_identity=governed_identity,
            governed_isin=None,
            state=IdentityResolutionState.GOVERNED_IDENTITY_INVALID,
            instrument=None,
            source_sha256=source_sha256,
            resolved_at=timestamp,
            blocker="DSI013_GOVERNED_IDENTITY_NOT_EXACT_NSE_ISIN",
        )

    matching = {
        (
            record.instrument_key,
            record.isin,
            record.exchange,
            record.segment,
            record.instrument_type,
            record.trading_symbol,
            record.exchange_token,
            record.name,
        ): record
        for record in records
        if record.isin == isin
        and record.exchange == "NSE"
        and record.segment == "NSE_EQ"
    }
    unique = tuple(matching.values())
    source_types = tuple(
        sorted({record.instrument_type for record in unique if record.instrument_type})
    )
    if not unique:
        return InstrumentResolution(
            governed_identity=governed_identity,
            governed_isin=isin,
            state=IdentityResolutionState.SOURCE_RECORD_MISSING,
            instrument=None,
            source_sha256=source_sha256,
            resolved_at=timestamp,
            blocker="DSI013_UPSTOX_EXACT_NSE_ISIN_NOT_FOUND",
            source_instrument_types=source_types,
        )
    canonical_keys = {record.instrument_key for record in unique}
    expected_key = f"NSE_EQ|{isin}"
    if len(canonical_keys) != 1:
        return InstrumentResolution(
            governed_identity=governed_identity,
            governed_isin=isin,
            state=IdentityResolutionState.SOURCE_RECORD_AMBIGUOUS,
            instrument=None,
            source_sha256=source_sha256,
            resolved_at=timestamp,
            blocker=f"DSI013_UPSTOX_INSTRUMENT_KEY_AMBIGUOUS:{len(canonical_keys)}",
            source_instrument_types=source_types,
        )
    selected = sorted(
        unique,
        key=lambda record: (
            0 if record.instrument_type == "EQ" else 1,
            record.instrument_type,
            record.instrument_key,
            record.trading_symbol,
            record.exchange_token,
            record.name,
        ),
    )[0]
    if selected.instrument_key != expected_key:
        return InstrumentResolution(
            governed_identity=governed_identity,
            governed_isin=isin,
            state=IdentityResolutionState.SOURCE_RECORD_CONTRACT_INVALID,
            instrument=None,
            source_sha256=source_sha256,
            resolved_at=timestamp,
            blocker=(
                "DSI013_UPSTOX_INSTRUMENT_KEY_NOT_ISIN_SCHEME:"
                f"{selected.instrument_key}"
            ),
            source_instrument_types=source_types,
        )
    return InstrumentResolution(
        governed_identity=governed_identity,
        governed_isin=isin,
        state=IdentityResolutionState.RESOLVED,
        instrument=selected,
        source_sha256=source_sha256,
        resolved_at=timestamp,
        source_instrument_types=source_types,
    )


def aggregate_intraday_session(
    bars: Sequence[IntradayBar],
    *,
    governed_identity: str,
    instrument_key: str,
    session_date: date,
) -> AggregatedIntradaySession | None:
    """Aggregate exactly one identity/instrument/session without cross-series mixing."""

    selected = sorted(
        (
            bar
            for bar in bars
            if bar.governed_identity == governed_identity
            and bar.instrument_key == instrument_key
            and bar.timestamp.date() == session_date
        ),
        key=lambda bar: bar.timestamp,
    )
    if not selected:
        return None
    return AggregatedIntradaySession(
        governed_identity=governed_identity,
        instrument_key=instrument_key,
        session_date=session_date,
        bar_count=len(selected),
        open=selected[0].open,
        high=max(bar.high for bar in selected),
        low=min(bar.low for bar in selected),
        close=selected[-1].close,
        volume=sum(bar.volume for bar in selected),
    )


def reconcile_raw_daily_session(
    bars: Sequence[IntradayBar],
    daily: DailyCandleReference,
    *,
    instrument_key: str,
    policy: IntradayExecutionPolicy | None = None,
    price_tolerance: float = PRICE_TOLERANCE,
    volume_tolerance: int = VOLUME_TOLERANCE,
) -> DailyReconciliationResult:
    """Reconcile one complete broker session to the governed raw daily candle."""

    active_policy = policy or IntradayExecutionPolicy()
    aggregate = aggregate_intraday_session(
        bars,
        governed_identity=daily.governed_identity,
        instrument_key=instrument_key,
        session_date=daily.session_date,
    )
    if aggregate is None:
        return DailyReconciliationResult(
            state=DailyReconciliationState.EMPTY_INTRADAY_SESSION,
            passed=False,
            blockers=("DSI013_INTRADAY_SESSION_EMPTY",),
            aggregate=None,
            metric_rows=(),
        )
    blockers: list[str] = []
    if aggregate.governed_identity != daily.governed_identity:
        blockers.append("DSI013_DAILY_INTRADAY_IDENTITY_MISMATCH")
    if aggregate.instrument_key != instrument_key:
        blockers.append("DSI013_DAILY_INTRADAY_INSTRUMENT_KEY_MISMATCH")
    if aggregate.session_date != daily.session_date:
        blockers.append("DSI013_DAILY_INTRADAY_SESSION_DATE_MISMATCH")
    if aggregate.bar_count != active_policy.expected_regular_bar_count:
        blockers.append(
            f"DSI013_DAILY_INTRADAY_REGULAR_SESSION_INCOMPLETE:{aggregate.bar_count}"
        )

    metric_rows: list[dict[str, Any]] = []
    for metric in ("open", "high", "low", "close"):
        actual = float(getattr(aggregate, metric))
        expected = float(getattr(daily, metric))
        delta = actual - expected
        passed = abs(delta) <= price_tolerance
        if not passed:
            blockers.append(f"DSI013_DAILY_INTRADAY_{metric.upper()}_MISMATCH")
        metric_rows.append(
            {
                "metric": metric,
                "expected": expected,
                "actual": actual,
                "delta": delta,
                "tolerance": price_tolerance,
                "passed": passed,
            }
        )
    volume_delta = aggregate.volume - daily.volume
    volume_passed = abs(volume_delta) <= volume_tolerance
    if not volume_passed:
        blockers.append("DSI013_DAILY_INTRADAY_VOLUME_MISMATCH")
    metric_rows.append(
        {
            "metric": "volume",
            "expected": daily.volume,
            "actual": aggregate.volume,
            "delta": volume_delta,
            "tolerance": volume_tolerance,
            "passed": volume_passed,
        }
    )

    state = _reconciliation_state(blockers)
    return DailyReconciliationResult(
        state=state,
        passed=not blockers,
        blockers=tuple(sorted(set(blockers))),
        aggregate=aggregate,
        metric_rows=tuple(metric_rows),
    )


def _reconciliation_state(blockers: Sequence[str]) -> DailyReconciliationState:
    if not blockers:
        return DailyReconciliationState.RECONCILED
    if any("IDENTITY_MISMATCH" in blocker for blocker in blockers):
        return DailyReconciliationState.IDENTITY_MISMATCH
    if any("INSTRUMENT_KEY_MISMATCH" in blocker for blocker in blockers):
        return DailyReconciliationState.INSTRUMENT_KEY_MISMATCH
    if any("SESSION_DATE_MISMATCH" in blocker for blocker in blockers):
        return DailyReconciliationState.SESSION_DATE_MISMATCH
    if any("REGULAR_SESSION_INCOMPLETE" in blocker for blocker in blockers):
        return DailyReconciliationState.INCOMPLETE_REGULAR_SESSION
    if any("VOLUME_MISMATCH" in blocker for blocker in blockers):
        return DailyReconciliationState.DAILY_VOLUME_MISMATCH
    return DailyReconciliationState.DAILY_OHLC_MISMATCH


def _governed_isin(governed_identity: str) -> str | None:
    prefix = "nse:isin:"
    if not governed_identity.startswith(prefix):
        return None
    isin = governed_identity[len(prefix) :]
    if len(isin) != 12 or not isin.isalnum() or isin.upper() != isin:
        return None
    return isin


__all__ = [
    "AggregatedIntradaySession",
    "DailyCandleReference",
    "DailyReconciliationResult",
    "DailyReconciliationState",
    "IdentityResolutionState",
    "InstrumentResolution",
    "PRICE_TOLERANCE",
    "UpstoxInstrumentRecord",
    "VOLUME_TOLERANCE",
    "aggregate_intraday_session",
    "instrument_source_sha256",
    "parse_upstox_instrument_payload",
    "reconcile_raw_daily_session",
    "resolve_upstox_nse_equity",
]
