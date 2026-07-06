from __future__ import annotations

from datetime import timedelta

import pytest

from alpha.market.timeframe import Timeframe


def test_string_representation() -> None:
    assert str(Timeframe.ONE_MINUTE) == "1m"
    assert str(Timeframe.FIVE_MINUTES) == "5m"
    assert str(Timeframe.ONE_HOUR) == "1h"
    assert str(Timeframe.ONE_DAY) == "1d"


def test_label_property() -> None:
    assert Timeframe.ONE_MINUTE.label == "1m"
    assert Timeframe.ONE_WEEK.label == "1w"


def test_duration_property() -> None:
    assert Timeframe.ONE_MINUTE.duration == timedelta(minutes=1)
    assert Timeframe.FIVE_MINUTES.duration == timedelta(minutes=5)
    assert Timeframe.ONE_HOUR.duration == timedelta(hours=1)
    assert Timeframe.ONE_DAY.duration == timedelta(days=1)
    assert Timeframe.ONE_WEEK.duration == timedelta(weeks=1)


def test_seconds_property() -> None:
    assert Timeframe.ONE_MINUTE.seconds == 60
    assert Timeframe.FIVE_MINUTES.seconds == 300
    assert Timeframe.FIFTEEN_MINUTES.seconds == 900
    assert Timeframe.THIRTY_MINUTES.seconds == 1800
    assert Timeframe.ONE_HOUR.seconds == 3600
    assert Timeframe.FOUR_HOURS.seconds == 14400
    assert Timeframe.ONE_DAY.seconds == 86400
    assert Timeframe.ONE_WEEK.seconds == 604800


def test_intraday_timeframes() -> None:
    assert Timeframe.ONE_MINUTE.is_intraday
    assert Timeframe.FIVE_MINUTES.is_intraday
    assert Timeframe.FIFTEEN_MINUTES.is_intraday
    assert Timeframe.THIRTY_MINUTES.is_intraday
    assert Timeframe.ONE_HOUR.is_intraday
    assert Timeframe.FOUR_HOURS.is_intraday


def test_daily_or_higher() -> None:
    assert not Timeframe.ONE_MINUTE.is_daily_or_higher
    assert not Timeframe.ONE_HOUR.is_daily_or_higher
    assert Timeframe.ONE_DAY.is_daily_or_higher
    assert Timeframe.ONE_WEEK.is_daily_or_higher


def test_all_supported_timeframes_are_time_based() -> None:
    for timeframe in Timeframe:
        assert timeframe.is_time_based


def test_parse_minute_timeframes() -> None:
    assert Timeframe.parse("1m") is Timeframe.ONE_MINUTE
    assert Timeframe.parse("5m") is Timeframe.FIVE_MINUTES
    assert Timeframe.parse("15m") is Timeframe.FIFTEEN_MINUTES
    assert Timeframe.parse("30m") is Timeframe.THIRTY_MINUTES


def test_parse_hour_timeframes() -> None:
    assert Timeframe.parse("1h") is Timeframe.ONE_HOUR
    assert Timeframe.parse("4h") is Timeframe.FOUR_HOURS


def test_parse_daily_timeframes() -> None:
    assert Timeframe.parse("1d") is Timeframe.ONE_DAY
    assert Timeframe.parse("1w") is Timeframe.ONE_WEEK


def test_parse_is_case_insensitive() -> None:
    assert Timeframe.parse("1D") is Timeframe.ONE_DAY
    assert Timeframe.parse("1W") is Timeframe.ONE_WEEK


def test_parse_strips_whitespace() -> None:
    assert Timeframe.parse(" 1m ") is Timeframe.ONE_MINUTE
    assert Timeframe.parse("\t1h\n") is Timeframe.ONE_HOUR


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2m",
        "10m",
        "45m",
        "2h",
        "daily",
        "minute",
        "abc",
    ],
)
def test_parse_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        Timeframe.parse(value)


def test_ordering() -> None:
    assert Timeframe.ONE_MINUTE < Timeframe.FIVE_MINUTES
    assert Timeframe.FIVE_MINUTES < Timeframe.FIFTEEN_MINUTES
    assert Timeframe.FIFTEEN_MINUTES < Timeframe.THIRTY_MINUTES
    assert Timeframe.THIRTY_MINUTES < Timeframe.ONE_HOUR
    assert Timeframe.ONE_HOUR < Timeframe.FOUR_HOURS
    assert Timeframe.FOUR_HOURS < Timeframe.ONE_DAY
    assert Timeframe.ONE_DAY < Timeframe.ONE_WEEK


def test_equality() -> None:
    assert Timeframe.ONE_DAY == Timeframe.ONE_DAY
    assert Timeframe.ONE_DAY != Timeframe.ONE_HOUR


def test_hashability() -> None:
    mapping = {
        Timeframe.ONE_DAY: "daily",
        Timeframe.ONE_HOUR: "hourly",
    }

    assert mapping[Timeframe.ONE_DAY] == "daily"
    assert mapping[Timeframe.ONE_HOUR] == "hourly"


def test_rank_increases_monotonically() -> None:
    ranks = [timeframe.rank for timeframe in Timeframe]

    assert ranks == sorted(ranks)


def test_seconds_match_duration() -> None:
    for timeframe in Timeframe:
        assert timeframe.seconds == int(timeframe.duration.total_seconds())


def test_enum_iteration_order_matches_rank() -> None:
    previous = None

    for timeframe in Timeframe:
        if previous is not None:
            assert previous < timeframe

        previous = timeframe
