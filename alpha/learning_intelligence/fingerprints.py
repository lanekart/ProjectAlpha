from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from alpha.learning_intelligence.models import SetupFingerprint
from alpha.performance_intelligence.models import RecommendationLedgerEntry


def fingerprint_from_ledger_entry(entry: RecommendationLedgerEntry) -> SetupFingerprint:
    indicators = dict(entry.key_indicator_snapshot)
    data = dict(entry.data_completeness_snapshot)
    return SetupFingerprint(
        final_verdict=entry.final_verdict,
        setup_type=entry.setup_type or "UNKNOWN",
        setup_state=entry.setup_state or "UNKNOWN",
        market_regime=entry.market_regime or "UNKNOWN",
        sector=entry.sector or "UNKNOWN",
        trend_regime=indicators.get("price_trend", "UNKNOWN"),
        volume_regime=_volume_regime(indicators.get("volume_score")),
        volatility_regime=_volatility_regime(indicators.get("atr")),
        relative_strength_regime=_relative_strength_regime(
            indicators.get("relative_strength") or indicators.get("relative_volume")
        ),
        candle_pattern=indicators.get("candle_pattern", "UNKNOWN"),
        breakout_retracement_state=_join_state(
            indicators.get("price_breakout"),
            indicators.get("retracement_state"),
        ),
        dma_alignment=_dma_alignment(indicators),
        data_completeness_level=data.get("data_quality", "UNKNOWN"),
    )


def fingerprint_from_recommendation(
    recommendation: Any,
    *,
    market_regime: str | None = None,
) -> SetupFingerprint:
    trade_plan = getattr(recommendation, "trade_plan", None)
    price_evidence = getattr(recommendation, "price_evidence", None)
    volume_evidence = getattr(recommendation, "volume_evidence", None)
    metadata = getattr(recommendation, "metadata", {})
    return SetupFingerprint(
        final_verdict=str(getattr(recommendation, "final_signal", "UNKNOWN")),
        setup_type=str(getattr(recommendation, "setup_name", "UNKNOWN")),
        setup_state=str(getattr(recommendation, "setup_stage", "UNKNOWN")),
        market_regime=market_regime or "UNKNOWN",
        sector=str(metadata.get("sector", "UNKNOWN")),
        trend_regime=str(getattr(price_evidence, "trend_state", "UNKNOWN")),
        volume_regime=_volume_regime(
            str(getattr(volume_evidence, "volume_score", "UNKNOWN"))
        ),
        volatility_regime=_volatility_regime(
            str(getattr(trade_plan, "atr_value", "UNKNOWN"))
        ),
        relative_strength_regime=_relative_strength_regime(
            str(getattr(trade_plan, "relative_volume", "UNKNOWN"))
        ),
        candle_pattern=str(getattr(trade_plan, "candle_pattern", "UNKNOWN")),
        breakout_retracement_state=_join_state(
            str(getattr(price_evidence, "breakout_state", "UNKNOWN")),
            str(getattr(price_evidence, "retracement_state", "UNKNOWN")),
        ),
        dma_alignment=_dma_alignment(
            {
                "dma_20": str(getattr(trade_plan, "dma_20_invalidation", "")),
                "dma_50": str(getattr(trade_plan, "dma_50", "")),
                "dma_200": str(getattr(trade_plan, "dma_200", "")),
            }
        ),
        data_completeness_level=str(metadata.get("data_quality", "UNKNOWN")),
    )


def _join_state(first: str | None, second: str | None) -> str:
    values = [value for value in (first, second) if value and value != "UNKNOWN"]
    return "+".join(values) if values else "UNKNOWN"


def _volume_regime(value: str | None) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "UNKNOWN"
    if decimal >= Decimal("0.70"):
        return "STRONG"
    if decimal >= Decimal("0.40"):
        return "NORMAL"
    return "WEAK"


def _volatility_regime(value: str | None) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "UNKNOWN"
    if decimal >= Decimal("5"):
        return "HIGH"
    if decimal >= Decimal("1"):
        return "NORMAL"
    return "LOW"


def _relative_strength_regime(value: str | None) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "UNKNOWN"
    if decimal >= Decimal("1.2"):
        return "STRONG"
    if decimal >= Decimal("0.8"):
        return "NORMAL"
    return "WEAK"


def _dma_alignment(indicators: dict[str, str]) -> str:
    dma_20 = _decimal(indicators.get("dma_20"))
    dma_50 = _decimal(indicators.get("dma_50"))
    dma_200 = _decimal(indicators.get("dma_200"))
    if dma_20 is None or dma_50 is None:
        return "UNKNOWN"
    if dma_200 is not None and dma_20 >= dma_50 >= dma_200:
        return "BULLISH"
    if dma_20 >= dma_50:
        return "CONSTRUCTIVE"
    return "BEARISH"


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    if value.strip().lower() in {"", "none", "unavailable", "unknown"}:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


__all__ = ["fingerprint_from_ledger_entry", "fingerprint_from_recommendation"]
