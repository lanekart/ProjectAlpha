from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from alpha.decision_superiority.intraday_entry_mechanisms import (
    IntradayEntryState,
    evaluate_intraday_entries,
)
from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayMechanismId,
)
from alpha.decision_superiority.intraday_execution_population import (
    IntradayCandidate,
)

IST = timezone(timedelta(hours=5, minutes=30))
IDENTITY = "nse:isin:INE000A01000"
INSTRUMENT_KEY = "NSE_EQ|INE000A01000"
SESSION_DATE = date(2024, 1, 3)


def _candidate() -> IntradayCandidate:
    return IntradayCandidate(
        signal_id="SIG-1",
        identity_key=IDENTITY,
        symbol="ALPHA",
        strategy_variant_id="STRATEGY-1",
        walk_forward_fold_id="WF-2024",
        regime="BULL",
        signal_date=date(2024, 1, 2),
        entry_session=SESSION_DATE,
        signal_strength=0.75,
        signed_raw_entry_price=100.0,
        signed_entry_price_after_slippage=100.1,
        initial_stop=95.0,
        target_1=110.0,
        target_2=115.0,
        maximum_holding_sessions=20,
        average_traded_value20=10_000_000.0,
    )


def _bars() -> list[IntradayBar]:
    start = datetime(2024, 1, 3, 9, 15, tzinfo=IST)
    return [
        IntradayBar(
            governed_identity=IDENTITY,
            instrument_key=INSTRUMENT_KEY,
            timestamp=start + timedelta(minutes=index * 5),
            open=100.0,
            high=100.5,
            low=99.5,
            close=100.0,
            volume=100,
        )
        for index in range(75)
    ]


def _fills(
    bars: list[IntradayBar],
    *,
    comparable_session_median_volume: float | None = None,
):
    return {
        fill.mechanism_id: fill
        for fill in evaluate_intraday_entries(
            _candidate(),
            bars,
            comparable_session_median_volume=comparable_session_median_volume,
        )
    }


def test_control_preserves_signed_dsi009_fill() -> None:
    fill = _fills(_bars())[IntradayMechanismId.NEXT_SESSION_OPEN]

    assert fill.state is IntradayEntryState.ENTERED
    assert fill.raw_fill_price == 100.0
    assert fill.fill_price_after_slippage == 100.1
    assert fill.raw_price_delta_vs_control == 0.0
    assert fill.fill_timestamp is not None
    assert fill.fill_timestamp.time().isoformat() == "09:15:00"


def test_orb15_uses_completed_close_and_next_bar_open() -> None:
    bars = _bars()
    bars[3] = replace(bars[3], high=101.2, close=101.0, volume=300)
    bars[4] = replace(bars[4], open=101.1, high=101.3, low=100.8, close=101.0)

    fill = _fills(bars)[IntradayMechanismId.ORB15_BREAKOUT]

    assert fill.state is IntradayEntryState.ENTERED
    assert fill.trigger_timestamp is not None
    assert fill.trigger_timestamp.time().isoformat() == "09:30:00"
    assert fill.fill_timestamp is not None
    assert fill.fill_timestamp.time().isoformat() == "09:35:00"
    assert fill.raw_fill_price == pytest.approx(101.1)
    assert fill.fill_price_after_slippage == pytest.approx(101.15055)
    assert fill.opening_range_high == pytest.approx(100.5)


def test_vwap_reclaim_requires_prior_below_and_volume_confirmation() -> None:
    bars = _bars()
    bars[3] = replace(bars[3], high=100.0, low=98.5, close=99.0, volume=100)
    bars[4] = replace(bars[4], high=101.0, low=99.5, close=100.8, volume=500)
    bars[5] = replace(bars[5], open=100.9, high=101.1, low=100.5, close=100.8)

    fill = _fills(bars)[IntradayMechanismId.VWAP_RECLAIM]

    assert fill.state is IntradayEntryState.ENTERED
    assert fill.trigger_timestamp is not None
    assert fill.trigger_timestamp.time().isoformat() == "09:35:00"
    assert fill.fill_timestamp is not None
    assert fill.fill_timestamp.time().isoformat() == "09:40:00"
    assert fill.raw_fill_price == pytest.approx(100.9)
    assert fill.trigger_vwap is not None


def test_first_pullback_uses_first_two_bar_low_volume_retracement() -> None:
    bars = _bars()
    bars[3] = replace(bars[3], high=101.2, low=99.8, close=101.0, volume=1_000)
    bars[4] = replace(bars[4], high=101.0, low=100.6, close=100.8, volume=100)
    bars[5] = replace(bars[5], high=100.9, low=100.5, close=100.7, volume=100)
    bars[6] = replace(bars[6], high=101.2, low=100.6, close=101.1, volume=150)
    bars[7] = replace(bars[7], open=101.2, high=101.4, low=101.0, close=101.3)

    fill = _fills(bars)[IntradayMechanismId.FIRST_PULLBACK]

    assert fill.state is IntradayEntryState.ENTERED
    assert fill.trigger_timestamp is not None
    assert fill.trigger_timestamp.time().isoformat() == "09:45:00"
    assert fill.fill_timestamp is not None
    assert fill.fill_timestamp.time().isoformat() == "09:50:00"
    assert fill.raw_fill_price == pytest.approx(101.2)


def test_closing_continuation_requires_comparable_volume_evidence() -> None:
    bars = _bars()
    bars[63] = replace(
        bars[63],
        high=101.1,
        low=100.0,
        close=101.0,
        volume=1_000,
    )
    bars[64] = replace(bars[64], open=101.2, high=101.3, low=100.9, close=101.1)

    unavailable = _fills(bars)[IntradayMechanismId.CLOSING_CONTINUATION]
    entered = _fills(
        bars,
        comparable_session_median_volume=5_000.0,
    )[IntradayMechanismId.CLOSING_CONTINUATION]

    assert unavailable.state is IntradayEntryState.DATA_UNAVAILABLE
    assert entered.state is IntradayEntryState.ENTERED
    assert entered.trigger_timestamp is not None
    assert entered.trigger_timestamp.time().isoformat() == "14:30:00"
    assert entered.fill_timestamp is not None
    assert entered.fill_timestamp.time().isoformat() == "14:35:00"
    assert entered.raw_fill_price == pytest.approx(101.2)


def test_standard_mechanism_rejects_fill_after_1430_cutoff() -> None:
    bars = _bars()
    bars[63] = replace(bars[63], high=101.2, close=101.0, volume=500)
    bars[64] = replace(bars[64], open=101.1)

    fill = _fills(bars)[IntradayMechanismId.ORB15_BREAKOUT]

    assert fill.state is IntradayEntryState.ENTRY_CUTOFF_EXCEEDED
    assert fill.fill_timestamp is None


def test_missing_opening_range_fails_orb_and_pullback_closed() -> None:
    bars = _bars()
    del bars[1]

    fills = _fills(bars)

    assert fills[IntradayMechanismId.ORB15_BREAKOUT].state is (
        IntradayEntryState.DATA_UNAVAILABLE
    )
    assert fills[IntradayMechanismId.FIRST_PULLBACK].state is (
        IntradayEntryState.DATA_UNAVAILABLE
    )
