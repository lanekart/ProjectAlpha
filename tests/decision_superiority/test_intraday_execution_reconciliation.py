from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionError,
)
from alpha.decision_superiority.intraday_execution_reconciliation import (
    DailyCandleReference,
    DailyReconciliationState,
    IdentityResolutionState,
    UpstoxInstrumentRecord,
    aggregate_intraday_session,
    instrument_source_sha256,
    parse_upstox_instrument_payload,
    reconcile_raw_daily_session,
    resolve_upstox_nse_equity,
)

IST = timezone(timedelta(hours=5, minutes=30))
IDENTITY = "nse:isin:INE000A01000"
INSTRUMENT_KEY = "NSE_EQ|INE000A01000"
SOURCE_HASH = "a" * 64


def _instrument(
    *,
    exchange: str = "NSE",
    segment: str = "NSE_EQ",
    isin: str = "INE000A01000",
    instrument_key: str = INSTRUMENT_KEY,
    instrument_type: str = "EQ",
    symbol: str = "ALPHA",
) -> UpstoxInstrumentRecord:
    return UpstoxInstrumentRecord(
        name="ALPHA LIMITED",
        exchange=exchange,
        segment=segment,
        isin=isin,
        instrument_key=instrument_key,
        exchange_token="123",
        trading_symbol=symbol,
        instrument_type=instrument_type,
    )


def _bars(
    *,
    count: int = 75,
    close_adjustment: float = 0.0,
    volume_adjustment: int = 0,
) -> tuple[IntradayBar, ...]:
    start = datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    rows: list[IntradayBar] = []
    for index in range(count):
        price = 100.0 + index / 100
        close = price + 0.05
        if index == count - 1:
            close += close_adjustment
        volume = 1_000 + index
        if index == count - 1:
            volume += volume_adjustment
        rows.append(
            IntradayBar(
                governed_identity=IDENTITY,
                instrument_key=INSTRUMENT_KEY,
                timestamp=start + timedelta(minutes=index * 5),
                open=price,
                high=max(price + 0.20, close),
                low=min(price - 0.20, close),
                close=close,
                volume=volume,
            )
        )
    return tuple(rows)


def _daily(*, close: float = 100.79, volume: int = 77_775) -> DailyCandleReference:
    return DailyCandleReference(
        governed_identity=IDENTITY,
        session_date=date(2024, 1, 2),
        open=100.0,
        high=100.94,
        low=99.8,
        close=close,
        volume=volume,
        price_basis="RAW",
        source_sha256=SOURCE_HASH,
    )


def test_parse_search_payload_and_resolve_exact_nse_isin() -> None:
    payload = {
        "status": "success",
        "data": [
            {
                "name": "ALPHA LIMITED",
                "exchange": "BSE",
                "segment": "BSE_EQ",
                "isin": "INE000A01000",
                "instrument_key": "BSE_EQ|INE000A01000",
                "exchange_token": "456",
                "trading_symbol": "ALPHA",
                "instrument_type": "EQ",
            },
            {
                "name": "ALPHA LIMITED",
                "exchange": "NSE",
                "segment": "NSE_EQ",
                "isin": "INE000A01000",
                "instrument_key": INSTRUMENT_KEY,
                "exchange_token": "123",
                "trading_symbol": "ALPHA",
                "instrument_type": "EQ",
            },
        ],
    }

    records = parse_upstox_instrument_payload(payload)
    resolution = resolve_upstox_nse_equity(
        IDENTITY,
        records,
        source_sha256=instrument_source_sha256(payload),
        resolved_at=datetime(2026, 7, 30, 16, 0, tzinfo=UTC),
    )

    assert resolution.state is IdentityResolutionState.RESOLVED
    assert resolution.instrument is not None
    assert resolution.instrument.instrument_key == INSTRUMENT_KEY
    assert resolution.governed_isin == "INE000A01000"
    assert resolution.source_instrument_types == ("EQ",)
    assert resolution.blocker is None


def test_resolver_accepts_be_only_cash_series() -> None:
    resolution = resolve_upstox_nse_equity(
        IDENTITY,
        (_instrument(instrument_type="BE"),),
        source_sha256=SOURCE_HASH,
    )

    assert resolution.state is IdentityResolutionState.RESOLVED
    assert resolution.instrument is not None
    assert resolution.instrument.instrument_type == "BE"
    assert resolution.source_instrument_types == ("BE",)


def test_resolver_prefers_eq_when_same_key_has_multiple_cash_series() -> None:
    resolution = resolve_upstox_nse_equity(
        IDENTITY,
        (
            _instrument(instrument_type="BE", symbol="ALPHA-BE"),
            _instrument(instrument_type="EQ", symbol="ALPHA"),
        ),
        source_sha256=SOURCE_HASH,
    )

    assert resolution.state is IdentityResolutionState.RESOLVED
    assert resolution.instrument is not None
    assert resolution.instrument.instrument_type == "EQ"
    assert resolution.source_instrument_types == ("BE", "EQ")


def test_resolver_rejects_noncanonical_or_ambiguous_keys() -> None:
    noncanonical = resolve_upstox_nse_equity(
        IDENTITY,
        (_instrument(instrument_key="NSE_EQ|123"),),
        source_sha256=SOURCE_HASH,
    )
    ambiguous = resolve_upstox_nse_equity(
        IDENTITY,
        (
            _instrument(instrument_key=INSTRUMENT_KEY, symbol="ALPHA"),
            _instrument(instrument_key="NSE_EQ|OTHER", symbol="ALPHA2"),
        ),
        source_sha256=SOURCE_HASH,
    )

    assert noncanonical.state is IdentityResolutionState.SOURCE_RECORD_CONTRACT_INVALID
    assert ambiguous.state is IdentityResolutionState.SOURCE_RECORD_AMBIGUOUS


def test_resolver_fails_closed_for_invalid_or_missing_identity() -> None:
    invalid = resolve_upstox_nse_equity(
        "nse:symbol:ALPHA",
        (_instrument(),),
        source_sha256=SOURCE_HASH,
    )
    missing = resolve_upstox_nse_equity(
        IDENTITY,
        (_instrument(isin="INE111A01000", instrument_key="NSE_EQ|INE111A01000"),),
        source_sha256=SOURCE_HASH,
    )

    assert invalid.state is IdentityResolutionState.GOVERNED_IDENTITY_INVALID
    assert missing.state is IdentityResolutionState.SOURCE_RECORD_MISSING


def test_aggregate_is_identity_and_instrument_isolated() -> None:
    bars = list(_bars(count=2))
    bars.append(
        IntradayBar(
            governed_identity="nse:isin:INE999A01000",
            instrument_key="NSE_EQ|INE999A01000",
            timestamp=datetime(2024, 1, 2, 9, 15, tzinfo=IST),
            open=500,
            high=510,
            low=490,
            close=505,
            volume=10_000,
        )
    )

    aggregate = aggregate_intraday_session(
        bars,
        governed_identity=IDENTITY,
        instrument_key=INSTRUMENT_KEY,
        session_date=date(2024, 1, 2),
    )

    assert aggregate is not None
    assert aggregate.bar_count == 2
    assert aggregate.open == pytest.approx(100.0)
    assert aggregate.high == pytest.approx(100.21)
    assert aggregate.volume == 2_001


def test_complete_raw_daily_reconciliation_passes() -> None:
    result = reconcile_raw_daily_session(
        _bars(),
        _daily(),
        instrument_key=INSTRUMENT_KEY,
    )

    assert result.state is DailyReconciliationState.RECONCILED
    assert result.passed is True
    assert result.blockers == ()
    assert result.aggregate is not None
    assert len(result.metric_rows) == 5
    assert all(bool(row["passed"]) for row in result.metric_rows)


def test_ohlc_mismatch_fails_closed() -> None:
    result = reconcile_raw_daily_session(
        _bars(close_adjustment=0.10),
        _daily(),
        instrument_key=INSTRUMENT_KEY,
    )

    assert result.state is DailyReconciliationState.DAILY_OHLC_MISMATCH
    assert result.passed is False
    assert "DSI013_DAILY_INTRADAY_CLOSE_MISMATCH" in result.blockers


def test_volume_mismatch_fails_closed() -> None:
    result = reconcile_raw_daily_session(
        _bars(volume_adjustment=1),
        _daily(),
        instrument_key=INSTRUMENT_KEY,
    )

    assert result.state is DailyReconciliationState.DAILY_VOLUME_MISMATCH
    assert result.passed is False
    assert "DSI013_DAILY_INTRADAY_VOLUME_MISMATCH" in result.blockers


def test_incomplete_regular_session_fails_closed() -> None:
    bars = _bars(count=74)
    aggregate = aggregate_intraday_session(
        bars,
        governed_identity=IDENTITY,
        instrument_key=INSTRUMENT_KEY,
        session_date=date(2024, 1, 2),
    )
    assert aggregate is not None
    daily = DailyCandleReference(
        governed_identity=IDENTITY,
        session_date=date(2024, 1, 2),
        open=aggregate.open,
        high=aggregate.high,
        low=aggregate.low,
        close=aggregate.close,
        volume=aggregate.volume,
        price_basis="RAW",
        source_sha256=SOURCE_HASH,
    )

    result = reconcile_raw_daily_session(
        bars,
        daily,
        instrument_key=INSTRUMENT_KEY,
    )

    assert result.state is DailyReconciliationState.INCOMPLETE_REGULAR_SESSION
    assert result.passed is False


def test_daily_reference_rejects_adjusted_basis() -> None:
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_DAILY_REFERENCE_MUST_BE_RAW",
    ):
        DailyCandleReference(
            governed_identity=IDENTITY,
            session_date=date(2024, 1, 2),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1000,
            price_basis="ADJUSTED",
            source_sha256=SOURCE_HASH,
        )
