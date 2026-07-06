from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from alpha.market.bar import Bar
from alpha.market.bar_series import BarSeries
from alpha.market.timeframe import Timeframe


def make_bar(ts: datetime, price: str = "100") -> Bar:
    return Bar(
        symbol="AAPL",
        timeframe=Timeframe.D1,
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


def test_barseries_constructs_successfully() -> None:
    now = datetime.now(UTC)

    series = BarSeries(
        [
            make_bar(now),
            make_bar(now + timedelta(days=1), "101"),
            make_bar(now + timedelta(days=2), "102"),
        ]
    )

    assert len(series) == 3
    assert series.symbol == "AAPL"
    assert series.timeframe == Timeframe.D1


def test_barseries_rejects_empty() -> None:
    with pytest.raises(ValueError):
        BarSeries([])


def test_barseries_rejects_mixed_symbols() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError):
        BarSeries(
            [
                make_bar(now),
                Bar(
                    symbol="TSLA",
                    timeframe=Timeframe.D1,
                    timestamp=now + timedelta(days=1),
                    open=Decimal("1"),
                    high=Decimal("1"),
                    low=Decimal("1"),
                    close=Decimal("1"),
                    volume=Decimal("1"),
                ),
            ]
        )


def test_barseries_rejects_non_monotonic_time() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError):
        BarSeries(
            [
                make_bar(now),
                make_bar(now - timedelta(days=1)),
            ]
        )


def test_head_tail_slicing() -> None:
    now = datetime.now(UTC)

    series = BarSeries(
        [
            make_bar(now),
            make_bar(now + timedelta(days=1), "101"),
            make_bar(now + timedelta(days=2), "102"),
            make_bar(now + timedelta(days=3), "103"),
        ]
    )

    head = series.head(2)
    tail = series.tail(2)

    assert len(head) == 2
    assert len(tail) == 2

    assert head.symbol == "AAPL"
    assert tail.symbol == "AAPL"


def test_slice_returns_new_series() -> None:
    now = datetime.now(UTC)

    series = BarSeries(
        [
            make_bar(now),
            make_bar(now + timedelta(days=1)),
            make_bar(now + timedelta(days=2)),
        ]
    )

    sliced = series[1:]

    assert isinstance(sliced, BarSeries)
    assert len(sliced) == 2


def test_between_time_filtering() -> None:
    now = datetime.now(UTC)

    b1 = make_bar(now)
    b2 = make_bar(now + timedelta(days=1))
    b3 = make_bar(now + timedelta(days=2))

    series = BarSeries([b1, b2, b3])

    filtered = series.between(
        now + timedelta(hours=1),
        now + timedelta(days=1, hours=1),
    )

    assert len(filtered) == 1
    assert filtered[0] == b2


def test_between_no_match_raises() -> None:
    now = datetime.now(UTC)

    series = BarSeries(
        [
            make_bar(now),
            make_bar(now + timedelta(days=1)),
        ]
    )

    with pytest.raises(ValueError):
        series.between(
            now + timedelta(days=10),
            now + timedelta(days=11),
        )


def test_contains_behavior() -> None:
    now = datetime.now(UTC)

    bar = make_bar(now)

    series = BarSeries([bar])

    assert bar in series


def test_immutability_contract() -> None:
    now = datetime.now(UTC)

    series = BarSeries(
        [
            make_bar(now),
            make_bar(now + timedelta(days=1)),
        ]
    )

    with pytest.raises(TypeError):
        series._bars = ()
