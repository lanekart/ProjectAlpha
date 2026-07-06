from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpha.market.timeframe import Timeframe


@dataclass(frozen=True, slots=True)
class Bar:
    """
    Immutable canonical OHLCV market data bar.

    A Bar represents a completed trading interval for a single
    instrument and timeframe.

    Invariants
    ----------
    - symbol is non-empty
    - timestamp is timezone-aware
    - open > 0
    - high > 0
    - low > 0
    - close > 0
    - volume >= 0
    - high >= open
    - high >= close
    - high >= low
    - low <= open
    - low <= close
    """

    symbol: str
    timeframe: Timeframe
    timestamp: datetime

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")

        if self.open <= Decimal("0"):
            raise ValueError("open must be > 0")

        if self.high <= Decimal("0"):
            raise ValueError("high must be > 0")

        if self.low <= Decimal("0"):
            raise ValueError("low must be > 0")

        if self.close <= Decimal("0"):
            raise ValueError("close must be > 0")

        if self.volume < 0:
            raise ValueError("volume cannot be negative")

        if self.high < self.open:
            raise ValueError("high cannot be less than open")

        if self.high < self.close:
            raise ValueError("high cannot be less than close")

        if self.high < self.low:
            raise ValueError("high cannot be less than low")

        if self.low > self.open:
            raise ValueError("low cannot exceed open")

        if self.low > self.close:
            raise ValueError("low cannot exceed close")

    @property
    def typical_price(self) -> Decimal:
        """
        Typical price used by many technical indicators.

        Formula
        -------
        (High + Low + Close) / 3
        """
        return (self.high + self.low + self.close) / Decimal("3")

    @property
    def hl2(self) -> Decimal:
        """
        Midpoint price.

        Formula
        -------
        (High + Low) / 2
        """
        return (self.high + self.low) / Decimal("2")

    @property
    def ohlc4(self) -> Decimal:
        """
        OHLC average.

        Formula
        -------
        (Open + High + Low + Close) / 4
        """
        return (self.open + self.high + self.low + self.close) / Decimal("4")

    @property
    def range(self) -> Decimal:
        """
        High-low trading range.
        """
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        """
        True if close >= open.
        """
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        """
        True if close < open.
        """
        return self.close < self.open
