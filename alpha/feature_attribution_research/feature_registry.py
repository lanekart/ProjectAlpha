"""Typed immutable registry for every requested research feature."""

from __future__ import annotations

from alpha.feature_attribution_research.models import (
    FEATURE_ENGINE_VERSION,
    DirectionalExpectation,
    FeatureAvailability,
    FeatureDefinition,
    FeatureGroup,
    MissingnessPolicy,
)


class FeatureRegistry:
    def __init__(self) -> None:
        self._definitions = _definitions()
        self._by_id = {item.feature_id: item for item in self._definitions}
        if len(self._by_id) != len(self._definitions):
            raise ValueError("feature registry contains duplicate feature ids")

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return self._definitions

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(item.feature_id for item in self._definitions)

    def get(self, feature_id: str) -> FeatureDefinition:
        try:
            return self._by_id[feature_id]
        except KeyError as error:
            raise KeyError(f"unregistered feature: {feature_id}") from error


def _definitions() -> tuple[FeatureDefinition, ...]:
    rows: list[FeatureDefinition] = []
    raw = "alpha.feature_attribution_research.point_in_time_builder"
    price = (
        ("distance_from_20ema", "%", 20, "POSITIVE"),
        ("distance_from_50ema", "%", 50, "POSITIVE"),
        ("distance_from_200ema", "%", 200, "POSITIVE"),
        ("ema20_slope", "normalized slope", 20, "POSITIVE"),
        ("ema50_slope", "normalized slope", 50, "POSITIVE"),
        ("ema200_slope", "normalized slope", 200, "POSITIVE"),
        ("ema20_above_ema50", "boolean", 50, "POSITIVE"),
        ("ema50_above_ema200", "boolean", 200, "POSITIVE"),
        ("close_position_in_20d_range", "ratio", 20, "POSITIVE"),
        ("close_position_in_60d_range", "ratio", 60, "POSITIVE"),
        ("distance_from_20d_high", "%", 20, "POSITIVE"),
        ("distance_from_60d_high", "%", 60, "POSITIVE"),
        ("distance_from_support", "%", 60, "NON_MONOTONIC"),
        ("distance_from_resistance", "%", 60, "NON_MONOTONIC"),
        ("support_density", "ratio", 60, "POSITIVE"),
        ("resistance_clearance", "%", 60, "POSITIVE"),
        ("higher_high_count", "count", 20, "POSITIVE"),
        ("higher_low_count", "count", 20, "POSITIVE"),
        ("swing_structure_score", "ratio", 20, "POSITIVE"),
    )
    trend = (
        ("positive_return_days_20d", "count", 20, "POSITIVE"),
        ("positive_return_days_60d", "count", 60, "POSITIVE"),
        ("trend_efficiency_20d", "ratio", 20, "POSITIVE"),
        ("trend_efficiency_60d", "ratio", 60, "POSITIVE"),
        ("directional_persistence", "ratio", 60, "POSITIVE"),
        ("price_regression_slope_20d", "normalized slope", 20, "POSITIVE"),
        ("price_regression_slope_60d", "normalized slope", 60, "POSITIVE"),
        ("trend_acceleration", "normalized slope", 60, "POSITIVE"),
        ("days_above_20ema", "count", 60, "POSITIVE"),
        ("days_above_50ema", "count", 60, "POSITIVE"),
        ("days_above_200ema", "count", 60, "POSITIVE"),
    )
    volume = (
        ("relative_volume_5d", "ratio", 20, "POSITIVE"),
        ("relative_volume_20d", "ratio", 40, "POSITIVE"),
        ("breakout_relative_volume", "ratio", 20, "POSITIVE"),
        ("volume_slope_20d", "normalized slope", 20, "POSITIVE"),
        ("volume_acceleration", "normalized slope", 40, "POSITIVE"),
        ("up_day_down_day_volume_ratio", "ratio", 20, "POSITIVE"),
        ("price_volume_confirmation", "correlation", 20, "POSITIVE"),
        ("turnover_20d", "INR", 20, "POSITIVE"),
        ("turnover_percentile", "percentile", None, "POSITIVE"),
        ("liquidity_persistence", "ratio", 60, "POSITIVE"),
        ("volume_concentration", "ratio", 20, "NON_MONOTONIC"),
        ("accumulation_volume_ratio", "ratio", 20, "POSITIVE"),
    )
    volatility = (
        ("atr_percent", "%", 14, "NON_MONOTONIC"),
        ("atr_percentile", "percentile", None, "NON_MONOTONIC"),
        ("realized_volatility_20d", "annualized volatility", 20, "NON_MONOTONIC"),
        ("realized_volatility_60d", "annualized volatility", 60, "NON_MONOTONIC"),
        ("volatility_contraction_20d", "ratio", 40, "POSITIVE"),
        ("volatility_contraction_60d", "ratio", 120, "POSITIVE"),
        ("volatility_expansion", "ratio", 20, "NON_MONOTONIC"),
        ("range_compression", "ratio", 20, "POSITIVE"),
        ("bollinger_bandwidth", "ratio", 20, "NON_MONOTONIC"),
        ("bandwidth_percentile", "percentile", None, "NON_MONOTONIC"),
        ("gap_frequency", "ratio", 60, "NEGATIVE"),
    )
    geometry = (
        ("base_duration", "sessions", 160, "NON_MONOTONIC"),
        ("base_depth", "%", 160, "NEGATIVE"),
        ("base_tightness", "ratio", 60, "POSITIVE"),
        ("base_slope", "normalized slope", 60, "NON_MONOTONIC"),
        ("contraction_count", "count", 60, "POSITIVE"),
        ("contraction_quality", "ratio", 60, "POSITIVE"),
        ("pivot_distance", "%", 60, "NON_MONOTONIC"),
        ("breakout_clearance", "%", 60, "POSITIVE"),
        ("consolidation_efficiency", "ratio", 60, "POSITIVE"),
        ("pre_breakout_extension", "%", 20, "NEGATIVE"),
    )
    feasibility = (
        ("prospective_stop_distance", "%", None, "NEGATIVE"),
        ("prospective_target_distance", "%", None, "POSITIVE"),
        ("prospective_reward_risk", "ratio", None, "POSITIVE"),
        ("entry_extension", "%", 20, "NEGATIVE"),
        ("expected_slippage_proxy", "diagnostic proxy", 20, "NEGATIVE"),
        ("average_traded_value", "INR", 20, "POSITIVE"),
        ("position_capacity_proxy", "INR", 20, "POSITIVE"),
        ("symbol_history_length", "sessions", None, "POSITIVE"),
    )
    for group, definitions in (
        (FeatureGroup.PRICE_STRUCTURE, price),
        (FeatureGroup.TREND_PERSISTENCE, trend),
        (FeatureGroup.VOLUME_TURNOVER, volume),
        (FeatureGroup.VOLATILITY, volatility),
        (FeatureGroup.BASE_GEOMETRY, geometry),
        (FeatureGroup.TRADE_FEASIBILITY, feasibility),
    ):
        rows.extend(
            _feature(
                name,
                group,
                unit,
                lookback,
                DirectionalExpectation(expectation),
                raw,
                lineage=("legacy_daily_ohlcv", group.value.lower()),
            )
            for name, unit, lookback, expectation in definitions
        )

    for name in (
        "relative_strength_20d",
        "relative_strength_60d",
        "relative_strength_slope",
        "relative_strength_percentile",
        "relative_strength_breakout",
    ):
        rows.append(
            _blocked(
                name,
                FeatureGroup.RELATIVE_STRENGTH,
                "Authoritative point-in-time benchmark history is absent from the "
                "legacy warehouse.",
            )
        )
    for name in (
        "benchmark_trend",
        "benchmark_above_200dma",
        "market_breadth",
        "market_volatility_state",
        "market_regime",
        "sector_strength",
        "sector_breadth",
    ):
        rows.append(
            _blocked(
                name,
                FeatureGroup.MARKET_CONTEXT,
                "Authoritative full-history point-in-time market or sector snapshots "
                "are unavailable.",
            )
        )
    component_names = (
        "price_structure_component",
        "volume_component",
        "trend_component",
        "relative_strength_component",
        "retracement_component",
        "candlestick_component",
        "breakout_component",
        "market_regime_component",
        "sector_component",
        "risk_component",
        "canonical_total_score",
    )
    sparse = {
        "price_structure_component",
        "volume_component",
        "retracement_component",
        "candlestick_component",
    }
    for name in component_names:
        available = name in sparse
        rows.append(
            FeatureDefinition(
                feature_id=name,
                feature_name=name.replace("_", " ").title(),
                feature_group=FeatureGroup.CANONICAL_COMPONENT,
                definition=(
                    "Frozen canonical recommendation component when it was persisted "
                    "at decision time."
                ),
                unit="normalized score"
                if name != "canonical_total_score"
                else "points",
                lookback=None,
                directional_expectation=DirectionalExpectation.POSITIVE,
                source_module="alpha.candidate_learning.CandidateDecisionRecord",
                source_lineage=(
                    "candidate_learning_ledger",
                    "recommendation_components",
                ),
                point_in_time_safe=True,
                missingness_policy=MissingnessPolicy.PRESERVE_MISSING,
                canonical_component=name,
                version="recommendation-engine-v1",
                availability=(
                    FeatureAvailability.PARTIALLY_AVAILABLE
                    if available or name == "canonical_total_score"
                    else FeatureAvailability.UNAVAILABLE
                ),
                limitation=(
                    "Sparse candidate-only history; unavailable for most "
                    "pre-association onsets."
                    if available or name == "canonical_total_score"
                    else "This canonical component was not persisted historically."
                ),
            )
        )
    return tuple(sorted(rows, key=lambda item: item.feature_id))


def _feature(
    name: str,
    group: FeatureGroup,
    unit: str,
    lookback: int | None,
    expectation: DirectionalExpectation,
    source: str,
    *,
    lineage: tuple[str, ...],
) -> FeatureDefinition:
    return FeatureDefinition(
        feature_id=name,
        feature_name=name.replace("_", " ").title(),
        feature_group=group,
        definition=(
            f"Point-in-time {name.replace('_', ' ')} computed using bars no later "
            "than onset."
        ),
        unit=unit,
        lookback=lookback,
        directional_expectation=expectation,
        source_module=source,
        source_lineage=lineage,
        point_in_time_safe=True,
        missingness_policy=MissingnessPolicy.PRESERVE_MISSING,
        canonical_component=None,
        version=FEATURE_ENGINE_VERSION,
    )


def _blocked(name: str, group: FeatureGroup, limitation: str) -> FeatureDefinition:
    return FeatureDefinition(
        feature_id=name,
        feature_name=name.replace("_", " ").title(),
        feature_group=group,
        definition=f"Requested {name.replace('_', ' ')} feature.",
        unit="unavailable",
        lookback=None,
        directional_expectation=DirectionalExpectation.UNKNOWN,
        source_module="unavailable",
        source_lineage=(),
        point_in_time_safe=False,
        missingness_policy=MissingnessPolicy.BLOCK_ANALYSIS,
        canonical_component=None,
        version=FEATURE_ENGINE_VERSION,
        availability=FeatureAvailability.UNAVAILABLE,
        limitation=limitation,
    )


__all__ = ["FeatureRegistry"]
