from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.market_opportunity_truth.models import (
    LiquidityState,
    RawOpportunityOnset,
    TradabilityAssessment,
    TrendState,
    VolatilityState,
)

_PERCENT = Decimal("100")
_TWO = Decimal("0.01")


class OpportunityTradabilityEngine:
    """Verify the frozen onset using only fields known on its onset date."""

    def assess(self, onset: RawOpportunityOnset) -> TradabilityAssessment:
        turnover = _input_decimal(onset, "average_turnover_20")
        ema20 = _input_decimal(onset, "ema_20")
        ema50 = _input_decimal(onset, "ema_50")
        atr = _input_decimal(onset, "atr_14")
        base_width = _input_decimal(onset, "base_width")
        extension = _input_decimal(onset, "extension_pct")
        relative_volume = _input_decimal(onset, "volume_ratio_20")
        future_flag = onset.input_value("future_return_used_for_detection")
        ordered = (
            onset.initial_stop < onset.entry < onset.reasonable_target
            and onset.initial_stop > 0
        )
        derived_rr = (
            Decimal("0")
            if not ordered
            else (onset.reasonable_target - onset.entry)
            / (onset.entry - onset.initial_stop)
        )
        reasons: list[str] = []
        if not ordered:
            reasons.append("STOP_ENTRY_TARGET_NOT_ORDERED")
        if onset.prospective_rr < Decimal("1.50") or derived_rr < Decimal("1.50"):
            reasons.append("PROSPECTIVE_REWARD_RISK_BELOW_1_5")
        if turnover is None:
            reasons.append("LIQUIDITY_UNAVAILABLE")
        elif turnover < Decimal("5000000"):
            reasons.append("TURNOVER_BELOW_FROZEN_TRADABILITY_MINIMUM")
        if extension is None:
            reasons.append("ENTRY_EXTENSION_UNAVAILABLE")
        elif extension > Decimal("0.10"):
            reasons.append("ENTRY_EXTENSION_ABOVE_10_PERCENT")
        if future_flag != "false":
            reasons.append("POINT_IN_TIME_CERTIFICATION_FAILED")
        if not onset.evidence_hash.strip():
            reasons.append("EVIDENCE_HASH_UNAVAILABLE")
        return TradabilityAssessment(
            tradable=not reasons,
            liquidity_turnover=turnover,
            liquidity_state=_liquidity_state(turnover),
            trend_state=_trend_state(onset.entry, ema20, ema50),
            volatility_state=_volatility_state(onset.entry, atr),
            atr_percent=_ratio_percent(atr, onset.entry),
            base_depth_percent=_percent(base_width),
            extension_percent=_percent(extension),
            relative_volume=relative_volume,
            reasons=tuple(reasons) if reasons else ("POINT_IN_TIME_TRADABLE",),
        )


def _liquidity_state(value: Decimal | None) -> LiquidityState:
    if value is None:
        return LiquidityState.UNKNOWN
    if value >= Decimal("100000000"):
        return LiquidityState.INSTITUTIONAL
    if value >= Decimal("50000000"):
        return LiquidityState.HIGH
    if value >= Decimal("20000000"):
        return LiquidityState.MEDIUM
    if value >= Decimal("5000000"):
        return LiquidityState.MINIMUM
    return LiquidityState.INSUFFICIENT


def _trend_state(
    entry: Decimal,
    ema20: Decimal | None,
    ema50: Decimal | None,
) -> TrendState:
    if ema20 is None:
        return TrendState.UNKNOWN
    if ema50 is not None and entry >= ema20 >= ema50:
        return TrendState.UP_ALIGNED
    if entry >= ema20:
        return TrendState.PRICE_ABOVE_EMA20
    return TrendState.NON_ALIGNED


def _volatility_state(
    entry: Decimal,
    atr: Decimal | None,
) -> VolatilityState:
    ratio = None if atr is None or entry <= 0 else atr / entry
    if ratio is None:
        return VolatilityState.UNKNOWN
    if ratio <= Decimal("0.03"):
        return VolatilityState.LOW
    if ratio <= Decimal("0.05"):
        return VolatilityState.NORMAL
    if ratio <= Decimal("0.08"):
        return VolatilityState.ELEVATED
    return VolatilityState.HIGH


def _input_decimal(onset: RawOpportunityOnset, key: str) -> Decimal | None:
    value = onset.input_value(key)
    if value is None or value in {"", "UNAVAILABLE"}:
        return None
    return Decimal(value)


def _ratio_percent(
    numerator: Decimal | None,
    denominator: Decimal,
) -> Decimal | None:
    if numerator is None or denominator <= 0:
        return None
    return (numerator / denominator * _PERCENT).quantize(_TWO, rounding=ROUND_HALF_UP)


def _percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return (value * _PERCENT).quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["OpportunityTradabilityEngine"]
