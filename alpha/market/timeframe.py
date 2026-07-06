from __future__ import annotations

from datetime import timedelta
from enum import IntEnum


class Timeframe(IntEnum):
    ONE_MINUTE = 60
    FIVE_MINUTES = 300
    FIFTEEN_MINUTES = 900
    THIRTY_MINUTES = 1800
    ONE_HOUR = 3600
    FOUR_HOURS = 14400
    ONE_DAY = 86400
    ONE_WEEK = 604800

    D1 = ONE_DAY

    @property
    def seconds(self) -> int:
        return int(self.value)

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    @property
    def is_intraday(self) -> bool:
        return self.seconds < Timeframe.ONE_DAY.seconds

    @property
    def is_time_based(self) -> bool:
        return True

    @property
    def is_daily_or_higher(self) -> bool:
        return not self.is_intraday

    @property
    def rank(self) -> int:
        order = (
            Timeframe.ONE_MINUTE,
            Timeframe.FIVE_MINUTES,
            Timeframe.FIFTEEN_MINUTES,
            Timeframe.THIRTY_MINUTES,
            Timeframe.ONE_HOUR,
            Timeframe.FOUR_HOURS,
            Timeframe.ONE_DAY,
            Timeframe.ONE_WEEK,
        )
        return order.index(self)

    def __str__(self) -> str:
        labels = {
            Timeframe.ONE_MINUTE: "1m",
            Timeframe.FIVE_MINUTES: "5m",
            Timeframe.FIFTEEN_MINUTES: "15m",
            Timeframe.THIRTY_MINUTES: "30m",
            Timeframe.ONE_HOUR: "1h",
            Timeframe.FOUR_HOURS: "4h",
            Timeframe.ONE_DAY: "1d",
            Timeframe.ONE_WEEK: "1w",
        }
        return labels[self]

    @property
    def label(self) -> str:
        return str(self)

    @classmethod
    def parse(cls, value: str) -> Timeframe:
        normalized = value.strip().lower()

        mapping = {
            "1m": cls.ONE_MINUTE,
            "5m": cls.FIVE_MINUTES,
            "15m": cls.FIFTEEN_MINUTES,
            "30m": cls.THIRTY_MINUTES,
            "1h": cls.ONE_HOUR,
            "4h": cls.FOUR_HOURS,
            "1d": cls.ONE_DAY,
            "1w": cls.ONE_WEEK,
        }

        if normalized not in mapping:
            raise ValueError(f"{value!r} is not a valid Timeframe")

        return mapping[normalized]
