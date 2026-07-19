"""Canonical Alpha baseline and empty TRL experiment templates."""

from __future__ import annotations

from decimal import Decimal

from alpha.recommendation_intelligence.engines import EvidenceScoringEngine
from alpha.tradingview_research.models import (
    PRODUCTION_INFLUENCE,
    TRL_SCHEMA_VERSION,
    CombinationMode,
    ComponentWeight,
    IndicatorId,
    IndicatorSetting,
    LabConfiguration,
    StrategyId,
    StrategySetting,
)

_CANONICAL_INDICATORS = {
    IndicatorId.EMA_TREND: True,
    IndicatorId.SMA_TREND: True,
    IndicatorId.VWAP: False,
    IndicatorId.RELATIVE_VOLUME: True,
    IndicatorId.VOLUME_MA: True,
    IndicatorId.ADX: False,
    IndicatorId.RSI: False,
    IndicatorId.MACD: False,
    IndicatorId.ATR: True,
    IndicatorId.PRICE_STRUCTURE: True,
    IndicatorId.RELATIVE_STRENGTH: True,
    IndicatorId.CANDLESTICK: True,
    IndicatorId.BREAKOUT: True,
    IndicatorId.RETRACEMENT: True,
    IndicatorId.SUPPORT: True,
    IndicatorId.RESISTANCE: True,
}


def canonical_baseline_configuration() -> LabConfiguration:
    """Extract the current Alpha weights into an immutable TRL baseline."""

    weights = EvidenceScoringEngine()._weights()
    return LabConfiguration(
        name="ALPHA_CANONICAL_BASELINE",
        indicators=tuple(
            IndicatorSetting(indicator=indicator, enabled=enabled)
            for indicator, enabled in _CANONICAL_INDICATORS.items()
        ),
        strategies=tuple(
            StrategySetting(strategy=strategy, enabled=True) for strategy in StrategyId
        ),
        combination_mode=CombinationMode.ANY,
        minimum_strategies=1,
        weights=tuple(
            ComponentWeight(component=name, weight=Decimal(weight) * Decimal("100"))
            for name, weight in weights.items()
        ),
        stop_model="ATR_BUFFERED_SUPPORT",
        exit_model="PARTIAL_2R_3R_4R",
        trend_timeframe="1W",
        setup_timeframe="1D",
        entry_timeframe="4H",
        universe="POINT_IN_TIME_ALPHA_UNIVERSE",
        sector_scope="ALL_AVAILABLE_SECTORS",
    )


def baseline_manifest() -> dict[str, object]:
    baseline = canonical_baseline_configuration()
    return {
        "configuration": baseline.as_dict(),
        "configuration_id": baseline.configuration_id,
        "limitations": [
            "TradingView chart data is not Alpha Market Truth Engine data.",
            (
                "VWAP, ADX, RSI, and MACD are research toggles and are "
                "disabled in baseline."
            ),
            "Baseline performance must be measured on each identical cohort.",
        ],
        "production_influence": PRODUCTION_INFLUENCE,
        "schema_version": TRL_SCHEMA_VERSION,
    }


def experiment_template() -> dict[str, object]:
    baseline = canonical_baseline_configuration()
    return {
        "baseline": baseline.as_dict(),
        "experiment_date": "YYYY-MM-DD",
        "experiment_id": "REPLACE_WITH_STABLE_EXPERIMENT_ID",
        "observations": [],
        "production_influence": False,
        "purpose": "State the hypothesis being tested against Alpha baseline.",
        "schema_version": TRL_SCHEMA_VERSION,
        "title": "TradingView research experiment",
        "treatment": baseline.as_dict(),
    }
