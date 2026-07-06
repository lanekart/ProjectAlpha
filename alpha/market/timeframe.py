from __future__ import annotations

from datetime import timedelta
from enum import IntEnum


class Timeframe(IntEnum):
    # Intraday
    ONE_MINUTE = 60
    FIVE_MINUTES = 300
    FIFTEEN_MINUTES = 900
    THIRTY_MINUTES = 1800
    ONE_HOUR = 3600
    FOUR_HOURS = 14400

    # Daily+
    ONE_DAY = 86400
    ONE_WEEK = 604800

    # Alias used by Bar model/tests
    D1 = ONE_DAY

    # -------------------------
    # Core properties
    # -------------------------
    @property
    def seconds(self) -> int:
        return int(self.value)

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.value)

    # -------------------------
    # Classification
    # -------------------------
    @property
    def is_intraday(self) -> bool:
        return self.value < self.ONE_DAY.value

    @property
    def is_time_based(self) -> bool:
        return True

    @property
    def is_daily_or_higher(self) -> bool:
        return self.value >= self.ONE_DAY.value

    # -------------------------
    # Ranking (monotonic order)
    # -------------------------
    @property
    def rank(self) -> int:
        order = [
            self.ONE_MINUTE,
            self.FIVE_MINUTES,
            self.FIFTEEN_MINUTES,
            self.THIRTY_MINUTES,
            self.ONE_HOUR,
            self.FOUR_HOURS,
            self.ONE_DAY,
            self.ONE_WEEK,
        ]
        return order.index(self)

    # -------------------------
    # Display
    # -------------------------
    def __str__(self) -> str:
        mapping = {
            self.ONE_MINUTE: "1m",
            self.FIVE_MINUTES: "5m",
            self.FIFTEEN_MINUTES: "15m",
            self.THIRTY_MINUTES: "30m",
            self.ONE_HOUR: "1h",
            self.FOUR_HOURS: "4h",
            self.ONE_DAY: "1d",
            self.ONE_WEEK: "1w",
        }
        return mapping[self]

    @property
    def label(self) -> str:
        return str(self)

    # -------------------------
    # Parsing
    # -------------------------
    @classmethod
    def parse(cls, value: str) -> Timeframe:
        if not isinstance(value, str):
            raise ValueError("Invalid timeframe")

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

    # ordering safety
    def __lt__(self, other: Timeframe) -> bool:
        if not isinstance(other, Timeframe):
            return NotImplemented
        return self.value < other.value
