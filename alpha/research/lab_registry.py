"""Versioned registries exposed to the conversational research compiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

REGISTRY_VERSION = "DSI-011-registry-v1.0.0"


class OutputType(StrEnum):
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    SERIES = "SERIES"


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    indicator_id: str
    aliases: tuple[str, ...]
    required_fields: tuple[str, ...]
    default_period: int | None
    warmup_period: int
    output_type: OutputType
    availability_timestamp: str
    price_basis: str
    implementation_version: str = REGISTRY_VERSION


@dataclass(frozen=True, slots=True)
class CandleDefinition:
    pattern_id: str
    aliases: tuple[str, ...]
    lookback: int
    availability_timestamp: str = "SESSION_CLOSE"
    implementation_version: str = REGISTRY_VERSION


@dataclass(frozen=True, slots=True)
class ExecutionRuleDefinition:
    rule_id: str
    aliases: tuple[str, ...]
    earliest_execution: str


def indicator_registry() -> dict[str, IndicatorDefinition]:
    definitions = (
        _indicator("SMA", ("simple moving average", "dma"), ("close",), 20, 20),
        _indicator("EMA", ("exponential moving average",), ("close",), 20, 20),
        _indicator("RSI", ("relative strength index",), ("close",), 14, 15),
        _indicator("ATR", ("average true range",), ("high", "low", "close"), 14, 15),
        _indicator(
            "ADX", ("average directional index",), ("high", "low", "close"), 14, 28
        ),
        _indicator(
            "PLUS_DI",
            ("+di", "positive directional indicator"),
            ("high", "low", "close"),
            14,
            15,
        ),
        _indicator(
            "MINUS_DI",
            ("-di", "negative directional indicator"),
            ("high", "low", "close"),
            14,
            15,
        ),
        _indicator(
            "MACD", ("moving average convergence divergence",), ("close",), 12, 35
        ),
        _indicator("MACD_SIGNAL", ("macd signal",), ("close",), 9, 35),
        _indicator("MACD_HISTOGRAM", ("macd histogram",), ("close",), 9, 35),
        _indicator("ROC", ("rate of change",), ("close",), 12, 13),
        _indicator(
            "STOCHASTIC", ("stochastic oscillator",), ("high", "low", "close"), 14, 15
        ),
        _indicator(
            "WILLIAMS_R",
            ("williams %r", "williams r"),
            ("high", "low", "close"),
            14,
            15,
        ),
        _indicator("BOLLINGER_UPPER", ("bollinger upper",), ("close",), 20, 20),
        _indicator("BOLLINGER_LOWER", ("bollinger lower",), ("close",), 20, 20),
        _indicator("BOLLINGER_WIDTH", ("bollinger band width",), ("close",), 20, 20),
        _indicator(
            "HISTORICAL_VOLATILITY", ("historical volatility",), ("close",), 20, 21
        ),
        _indicator(
            "VOLUME_SMA",
            ("volume moving average", "average volume"),
            ("volume",),
            20,
            20,
        ),
        _indicator(
            "VOLUME_RATIO", ("volume expansion", "volume ratio"), ("volume",), 20, 20
        ),
        _indicator(
            "LOOKBACK_HIGH", ("lookback high", "breakout high"), ("high",), 20, 20
        ),
        _indicator("LOOKBACK_LOW", ("lookback low", "breakdown low"), ("low",), 20, 20),
        _indicator(
            "DISTANCE_FROM_MA_PERCENT",
            ("distance from moving average",),
            ("close",),
            20,
            20,
        ),
        _indicator(
            "DISTANCE_FROM_MA_ATR",
            ("distance from moving average in atr",),
            ("high", "low", "close"),
            20,
            21,
        ),
        _indicator(
            "WEEK52_HIGH_DISTANCE",
            ("52-week high distance",),
            ("high", "close"),
            252,
            252,
        ),
        _indicator(
            "WEEK52_LOW_DISTANCE", ("52-week low distance",), ("low", "close"), 252, 252
        ),
        _indicator("SWING_HIGH", ("swing high", "resistance"), ("high",), 10, 10),
        _indicator("SWING_LOW", ("swing low", "support"), ("low",), 10, 10),
    )
    return {item.indicator_id: item for item in definitions}


def candle_registry() -> dict[str, CandleDefinition]:
    ids = {
        "BULLISH_CANDLE": ("bullish candle",),
        "BEARISH_CANDLE": ("bearish candle",),
        "DOJI": ("doji",),
        "HAMMER": ("hammer",),
        "INVERTED_HAMMER": ("inverted hammer",),
        "SHOOTING_STAR": ("shooting star",),
        "MARUBOZU": ("marubozu",),
        "SPINNING_TOP": ("spinning top",),
        "LONG_UPPER_WICK": ("long upper wick",),
        "LONG_LOWER_WICK": ("long lower wick",),
        "WIDE_RANGE": ("wide-range candle", "wide range candle"),
        "NARROW_RANGE": ("narrow-range candle", "narrow range candle"),
        "INSIDE_BAR": ("inside bar",),
        "OUTSIDE_BAR": ("outside bar",),
        "BULLISH_ENGULFING": ("bullish engulfing",),
        "BEARISH_ENGULFING": ("bearish engulfing",),
        "MORNING_STAR": ("morning star",),
        "EVENING_STAR": ("evening star",),
        "PIERCING_PATTERN": ("piercing pattern",),
        "DARK_CLOUD_COVER": ("dark-cloud cover", "dark cloud cover"),
        "THREE_WHITE_SOLDIERS": ("three white soldiers",),
        "THREE_BLACK_CROWS": ("three black crows",),
        "INSIDE_BAR_BREAKOUT": ("inside-bar breakout", "inside bar breakout"),
        "FAILED_BREAKOUT": ("failed breakout",),
        "CLOSE_TOP_20_PERCENT": ("close in the top 20%", "top 20% of its range"),
    }
    result: dict[str, CandleDefinition] = {}
    multi = {
        "BULLISH_ENGULFING",
        "BEARISH_ENGULFING",
        "MORNING_STAR",
        "EVENING_STAR",
        "PIERCING_PATTERN",
        "DARK_CLOUD_COVER",
        "THREE_WHITE_SOLDIERS",
        "THREE_BLACK_CROWS",
        "INSIDE_BAR_BREAKOUT",
        "FAILED_BREAKOUT",
    }
    for pattern_id, aliases in ids.items():
        result[pattern_id] = CandleDefinition(
            pattern_id=pattern_id,
            aliases=aliases,
            lookback=3 if pattern_id in multi else 1,
        )
    return result


def entry_registry() -> dict[str, ExecutionRuleDefinition]:
    rows = (
        (
            "NEXT_VALID_SESSION_OPEN",
            ("next open", "next session open"),
            "NEXT_SESSION_OPEN",
        ),
        (
            "NEXT_VALID_SESSION_CLOSE",
            ("next close", "next session close"),
            "NEXT_SESSION_CLOSE",
        ),
        ("DELAYED_SESSION_OPEN", ("wait", "delay"), "N_SESSIONS_LATER_OPEN"),
        (
            "BREAKOUT_ABOVE_SIGNAL_HIGH",
            ("breaks above the signal candle high",),
            "AFTER_SIGNAL",
        ),
        (
            "PERCENT_RETRACEMENT_LIMIT",
            ("retracement from the signal close",),
            "AFTER_SIGNAL",
        ),
        ("ATR_RETRACEMENT_LIMIT", ("atr retracement",), "AFTER_SIGNAL"),
    )
    return {
        rule_id: ExecutionRuleDefinition(rule_id, aliases, earliest)
        for rule_id, aliases, earliest in rows
    }


STOP_IDS = frozenset(
    {
        "FIXED_PERCENT",
        "ATR",
        "SIGNAL_CANDLE_LOW",
        "PREVIOUS_SESSION_LOW",
        "SWING_LOW",
        "SUPPORT",
        "BREAKOUT_LEVEL",
        "STOP-STRUCTURAL-10D",
        "TRAILING_PERCENT",
        "TRAILING_ATR",
        "TRAILING_SWING_LOW",
        "MOVING_AVERAGE_EXIT",
        "HIGHEST_CLOSE_TRAIL",
        "HIGHEST_HIGH_TRAIL",
        "BREAKEVEN_AFTER_GAIN",
        "SIGNAL_REVERSAL",
        "REGIME_REVERSAL",
    }
)

TARGET_IDS = frozenset(
    {
        "FIXED_PERCENT",
        "R_MULTIPLE",
        "ATR_MULTIPLE",
        "SWING_HIGH",
        "RESISTANCE",
        "RANGE_PROJECTION",
        "BREAKOUT_PROJECTION",
        "SIGNAL_REVERSAL",
        "REGIME_REVERSAL",
        "MOVING_AVERAGE_EXIT",
    }
)


def _indicator(
    indicator_id: str,
    aliases: tuple[str, ...],
    fields: tuple[str, ...],
    period: int,
    warmup: int,
) -> IndicatorDefinition:
    return IndicatorDefinition(
        indicator_id=indicator_id,
        aliases=aliases,
        required_fields=fields,
        default_period=period,
        warmup_period=warmup,
        output_type=OutputType.NUMBER,
        availability_timestamp="SESSION_CLOSE",
        price_basis="FULLY_ADJUSTED",
    )


__all__ = [
    "REGISTRY_VERSION",
    "STOP_IDS",
    "TARGET_IDS",
    "CandleDefinition",
    "ExecutionRuleDefinition",
    "IndicatorDefinition",
    "OutputType",
    "candle_registry",
    "entry_registry",
    "indicator_registry",
]
