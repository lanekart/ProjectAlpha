from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alpha.market.bar import Bar
from alpha.market.timeframe import Timeframe


def make_bar(**overrides: object) -> Bar:
    values: dict[str, object] = {
        "symbol": "AAPL",
        "timeframe": Timeframe.ONE_DAY,
        "timestamp": datetime.now(UTC),
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("95"),
        "close": Decimal("105"),
        "volume": 1_000,
    }

    values.update(overrides)

    return Bar(**values)


def test_create_valid_bar() -> None:
    bar = make_bar()

    assert bar.symbol == "AAPL"
    assert bar.timeframe is Timeframe.ONE_DAY
    assert bar.open == Decimal("100")
    assert bar.high == Decimal("110")
    assert bar.low == Decimal("95")
    assert bar.close == Decimal("105")
    assert bar.volume == 1_000


def test_symbol_cannot_be_empty() -> None:
    with pytest.raises(ValueError):
        make_bar(symbol="")


def test_symbol_cannot_be_whitespace() -> None:
    with pytest.raises(ValueError):
        make_bar(symbol="   ")


def test_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        make_bar(timestamp=datetime.now())


@pytest.mark.parametrize(
    "field",
    [
        "open",
        "high",
        "low",
        "close",
    ],
)
def test_prices_must_be_positive(field: str) -> None:
    kwargs = {field: Decimal("0")}

    with pytest.raises(ValueError):
        make_bar(**kwargs)


def test_volume_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        make_bar(volume=-1)


def test_high_cannot_be_less_than_open() -> None:
    with pytest.raises(ValueError):
        make_bar(
            open=Decimal("100"),
            high=Decimal("99"),
        )


def test_high_cannot_be_less_than_close() -> None:
    with pytest.raises(ValueError):
        make_bar(
            close=Decimal("100"),
            high=Decimal("99"),
        )


def test_high_cannot_be_less_than_low() -> None:
    with pytest.raises(ValueError):
        make_bar(
            low=Decimal("100"),
            high=Decimal("99"),
        )


def test_low_cannot_exceed_open() -> None:
    with pytest.raises(ValueError):
        make_bar(
            open=Decimal("100"),
            low=Decimal("101"),
            high=Decimal("110"),
        )


def test_low_cannot_exceed_close() -> None:
    with pytest.raises(ValueError):
        make_bar(
            close=Decimal("100"),
            low=Decimal("101"),
            high=Decimal("110"),
        )


def test_typical_price() -> None:
    bar = make_bar()

    expected = Decimal("103.3333333333333333333333333")

    assert bar.typical_price == expected


def test_hl2() -> None:
    bar = make_bar()

    assert bar.hl2 == Decimal("102.5")


def test_ohlc4() -> None:
    bar = make_bar()

    assert bar.ohlc4 == Decimal("102.5")


def test_range() -> None:
    bar = make_bar()

    assert bar.range == Decimal("15")


def test_bullish_bar() -> None:
    assert make_bar().is_bullish
    assert not make_bar().is_bearish


def test_bearish_bar() -> None:
    bar = make_bar(
        open=Decimal("110"),
        high=Decimal("112"),
        low=Decimal("95"),
        close=Decimal("100"),
    )

    assert bar.is_bearish
    assert not bar.is_bullish


def test_hashable() -> None:
    bar = make_bar()

    mapping = {
        bar: "daily",
    }

    assert mapping[bar] == "daily"


def test_equality() -> None:
    timestamp = datetime.now(UTC)

    left = make_bar(timestamp=timestamp)

    right = make_bar(timestamp=timestamp)

    assert left == right


def test_inequality() -> None:
    timestamp = datetime.now(UTC)

    left = make_bar(timestamp=timestamp)

    right = make_bar(
        timestamp=timestamp,
        close=Decimal("106"),
    )

    assert left != right
