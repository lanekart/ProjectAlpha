"""Bounded, interpretable two-feature interaction audit."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from decimal import Decimal

import numpy as np

from alpha.feature_attribution_research.models import (
    EvidencePartition,
    FeatureScalar,
    FeatureSnapshot,
    InteractionResult,
    OutcomeRecord,
)


class FeatureInteractionEngine:
    def analyze(
        self,
        *,
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        minimum_support: int = 50,
    ) -> tuple[InteractionResult, ...]:
        outcomes_by_id = {item.onset_id: item for item in outcomes}
        thresholds = _thresholds(snapshots)
        definitions = _definitions(thresholds)
        results = []
        for interaction_id, first, second, predicate in definitions:
            partition_signs = []
            temporary = []
            for partition in EvidencePartition:
                eligible = []
                baseline = []
                for snapshot in snapshots:
                    if snapshot.partition is not partition:
                        continue
                    outcome = outcomes_by_id.get(snapshot.onset_id)
                    if outcome is None or outcome.target_before_stop is None:
                        continue
                    baseline.append(outcome.target_before_stop)
                    value_a = _numeric(snapshot.value(first))
                    value_b = _numeric(snapshot.value(second))
                    if (
                        value_a is not None
                        and value_b is not None
                        and predicate(value_a, value_b)
                    ):
                        eligible.append(outcome.target_before_stop)
                winner_rate = _rate(eligible)
                baseline_rate = _rate(baseline)
                difference = (
                    None
                    if winner_rate is None or baseline_rate is None
                    else winner_rate - baseline_rate
                )
                if len(eligible) >= minimum_support and difference is not None:
                    partition_signs.append(
                        1 if difference > 0 else -1 if difference < 0 else 0
                    )
                temporary.append(
                    (partition, len(eligible), winner_rate, baseline_rate, difference)
                )
            stable = (
                len(partition_signs) == 3
                and len(set(partition_signs)) == 1
                and partition_signs[0] != 0
            )
            for partition, support, winner_rate, baseline_rate, difference in temporary:
                accepted = support >= minimum_support and stable
                results.append(
                    InteractionResult(
                        interaction_id=interaction_id,
                        feature_a=first,
                        feature_b=second,
                        partition=partition,
                        sample_count=support,
                        winner_rate=_optional_decimal(winner_rate),
                        baseline_winner_rate=_optional_decimal(baseline_rate),
                        incremental_win_rate=_optional_decimal(difference),
                        stable_sign=stable,
                        accepted_for_research=accepted,
                        limitation=(
                            None
                            if accepted
                            else (
                                "Insufficient support or inconsistent chronological "
                                "sign."
                            )
                        ),
                    )
                )
        return tuple(results)


Predicate = Callable[[float, float], bool]


def _definitions(
    thresholds: Mapping[str, tuple[float, float, float]],
) -> tuple[tuple[str, str, str, Predicate], ...]:
    def q(feature: str, index: int) -> float:
        values = thresholds.get(feature)
        return math.nan if values is None else values[index]

    return (
        (
            "trend_x_volume",
            "price_regression_slope_60d",
            "relative_volume_20d",
            lambda first, second: (
                first >= q("price_regression_slope_60d", 1)
                and second >= q("relative_volume_20d", 1)
            ),
        ),
        (
            "price_structure_x_volume",
            "swing_structure_score",
            "relative_volume_20d",
            lambda first, second: (
                first >= q("swing_structure_score", 1)
                and second >= q("relative_volume_20d", 1)
            ),
        ),
        (
            "volatility_contraction_x_breakout_volume",
            "volatility_contraction_20d",
            "breakout_relative_volume",
            lambda first, second: (
                first <= q("volatility_contraction_20d", 0)
                and second >= q("breakout_relative_volume", 2)
            ),
        ),
        (
            "relative_strength_x_market_regime",
            "relative_strength_60d",
            "market_regime_component",
            lambda first, second: (
                first >= q("relative_strength_60d", 1)
                and second >= q("market_regime_component", 1)
            ),
        ),
        (
            "prospective_rr_x_entry_extension",
            "prospective_reward_risk",
            "entry_extension",
            lambda first, second: (
                first >= q("prospective_reward_risk", 1)
                and second <= q("entry_extension", 1)
            ),
        ),
        (
            "base_duration_x_base_depth",
            "base_duration",
            "base_depth",
            lambda first, second: (
                first >= q("base_duration", 1) and second <= q("base_depth", 1)
            ),
        ),
        (
            "trend_persistence_x_market_breadth",
            "directional_persistence",
            "market_breadth",
            lambda first, second: (
                first >= q("directional_persistence", 1)
                and second >= q("market_breadth", 1)
            ),
        ),
        (
            "liquidity_x_volatility",
            "average_traded_value",
            "atr_percent",
            lambda first, second: (
                first >= q("average_traded_value", 1) and second <= q("atr_percent", 1)
            ),
        ),
    )


def _thresholds(
    snapshots: tuple[FeatureSnapshot, ...],
) -> dict[str, tuple[float, float, float]]:
    features = {
        "price_regression_slope_60d",
        "relative_volume_20d",
        "swing_structure_score",
        "volatility_contraction_20d",
        "breakout_relative_volume",
        "relative_strength_60d",
        "market_regime_component",
        "prospective_reward_risk",
        "entry_extension",
        "base_duration",
        "base_depth",
        "directional_persistence",
        "market_breadth",
        "average_traded_value",
        "atr_percent",
    }
    result: dict[str, tuple[float, float, float]] = {}
    for feature in features:
        values = np.asarray(
            [
                value
                for item in snapshots
                if item.partition is EvidencePartition.DEVELOPMENT
                and (value := _numeric(item.value(feature))) is not None
            ],
            dtype=float,
        )
        if values.size >= 4:
            quantiles = np.quantile(values, (0.25, 0.50, 0.75))
            result[feature] = (
                float(quantiles[0]),
                float(quantiles[1]),
                float(quantiles[2]),
            )
    return result


def _rate(values: list[bool]) -> float | None:
    return None if not values else sum(values) / len(values)


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


__all__ = ["FeatureInteractionEngine"]
