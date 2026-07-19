"""Conditional attribution and Simpson's-paradox diagnostics."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping
from decimal import Decimal

import numpy as np

from alpha.feature_attribution_research.models import (
    AttributionDirection,
    ConditionalAttributionResult,
    EvidencePartition,
    FeatureDefinition,
    FeatureScalar,
    FeatureSnapshot,
    OutcomeRecord,
    ResearchPopulationRecord,
)
from alpha.feature_attribution_research.outcome_labels import outcome_value
from alpha.feature_attribution_research.univariate import auc_score


class ConditionalAttributionEngine:
    def analyze(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        population: tuple[ResearchPopulationRecord, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        outcomes: tuple[OutcomeRecord, ...],
        outcome_id: str = "TARGET_BEFORE_STOP",
        minimum_support: int = 50,
    ) -> tuple[ConditionalAttributionResult, ...]:
        population_by_id = {item.onset_id: item for item in population}
        outcome_by_id = {item.onset_id: item for item in outcomes}
        contexts = _contexts(snapshots)
        context_values = {
            snapshot.onset_id: tuple(
                (name, context(snapshot, population_row))
                for name, context in contexts.items()
            )
            for snapshot in snapshots
            if (population_row := population_by_id.get(snapshot.onset_id)) is not None
        }
        results = []
        for definition in definitions:
            if not definition.point_in_time_safe:
                continue
            overall_rows: list[tuple[float, bool]] = []
            grouped_contexts: dict[str, dict[str, list[tuple[float, bool]]]] = {
                name: defaultdict(list) for name in contexts
            }
            for snapshot in snapshots:
                feature = _numeric(snapshot.value(definition.feature_id))
                outcome = outcome_by_id.get(snapshot.onset_id)
                values = context_values.get(snapshot.onset_id)
                if feature is None or outcome is None or values is None:
                    continue
                label = _binary(outcome_value(outcome, outcome_id))
                if label is None:
                    continue
                row = (feature, label)
                overall_rows.append(row)
                for context_name, context_value in values:
                    grouped_contexts[context_name][context_value].append(row)
            overall = tuple(overall_rows)
            overall_auc = _auc(overall)
            overall_sign = _sign(overall_auc)
            for context_name, grouped in grouped_contexts.items():
                supported_signs = []
                temporary = []
                for context_value in sorted(grouped):
                    rows = tuple(grouped[context_value])
                    auc = _auc(rows) if len(rows) >= minimum_support else None
                    sign = _sign(auc)
                    if sign != 0:
                        supported_signs.append(sign)
                    temporary.append((context_value, rows, auc, sign))
                majority_sign = _majority_sign(supported_signs)
                simpson = (
                    overall_sign != 0
                    and majority_sign != 0
                    and overall_sign != majority_sign
                    and len(supported_signs) >= 2
                )
                for context_value, rows, auc, sign in temporary:
                    results.append(
                        ConditionalAttributionResult(
                            feature_id=definition.feature_id,
                            outcome_id=outcome_id,
                            context_name=context_name,
                            context_value=context_value,
                            sample_count=len(rows),
                            effect=(None if auc is None else Decimal(str(2 * auc - 1))),
                            auc=None if auc is None else Decimal(str(auc)),
                            direction=_direction(auc),
                            sign_consistent=(
                                None
                                if auc is None or overall_sign == 0 or sign == 0
                                else sign == overall_sign
                            ),
                            simpson_paradox=simpson,
                        )
                    )
        return tuple(results)


ContextFunction = Callable[[FeatureSnapshot, ResearchPopulationRecord], str]


def _contexts(
    snapshots: tuple[FeatureSnapshot, ...],
) -> Mapping[str, ContextFunction]:
    liquidity = _development_quantiles(snapshots, "average_traded_value")
    volatility = _development_quantiles(snapshots, "atr_percent")
    return {
        "market_partition": lambda snapshot, population: snapshot.partition.value,
        "event_family": lambda snapshot, population: population.event_family,
        "canonical_setup": lambda snapshot, population: (
            population.canonical_setup or "UNAVAILABLE"
        ),
        "market_regime": lambda snapshot, population: str(
            snapshot.value("market_regime") or "UNAVAILABLE"
        ),
        "liquidity_bucket": lambda snapshot, population: _quantile_bucket(
            snapshot.value("average_traded_value"), liquidity
        ),
        "volatility_bucket": lambda snapshot, population: _quantile_bucket(
            snapshot.value("atr_percent"), volatility
        ),
        "trend_state": lambda snapshot, population: _trend_state(snapshot),
        "entry_extension_bucket": lambda snapshot, population: _extension_bucket(
            snapshot.value("entry_extension")
        ),
        "symbol_history_length": lambda snapshot, population: _history_bucket(
            snapshot.value("symbol_history_length")
        ),
    }


def _development_quantiles(
    snapshots: tuple[FeatureSnapshot, ...], feature_id: str
) -> tuple[float, ...]:
    values = np.asarray(
        [
            value
            for item in snapshots
            if item.partition is EvidencePartition.DEVELOPMENT
            and (value := _numeric(item.value(feature_id))) is not None
        ],
        dtype=float,
    )
    if values.size < 4:
        return ()
    return tuple(float(item) for item in np.quantile(values, (0.25, 0.50, 0.75)))


def _auc(rows: tuple[tuple[float, bool], ...]) -> float | None:
    if not rows:
        return None
    return auc_score(
        np.asarray([item[0] for item in rows], dtype=float),
        np.asarray([item[1] for item in rows], dtype=bool),
    )


def _direction(auc: float | None) -> AttributionDirection:
    if auc is None:
        return AttributionDirection.NO_EVIDENCE
    if auc >= 0.55:
        return AttributionDirection.POSITIVE
    if auc <= 0.45:
        return AttributionDirection.NEGATIVE
    return AttributionDirection.NO_EVIDENCE


def _sign(auc: float | None) -> int:
    if auc is None or abs(auc - 0.5) < 0.02:
        return 0
    return 1 if auc > 0.5 else -1


def _majority_sign(values: list[int]) -> int:
    total = sum(values)
    return 1 if total > 0 else -1 if total < 0 else 0


def _quantile_bucket(value: FeatureScalar, cutoffs: tuple[float, ...]) -> str:
    parsed = _numeric(value)
    if parsed is None or not cutoffs:
        return "UNAVAILABLE"
    return f"Q{int(np.searchsorted(cutoffs, parsed, side='right')) + 1}"


def _trend_state(snapshot: FeatureSnapshot) -> str:
    first = snapshot.value("ema20_above_ema50")
    second = snapshot.value("ema50_above_ema200")
    if first is True and second is True:
        return "ALIGNED_UP"
    if first is False and second is False:
        return "ALIGNED_DOWN"
    if first is None or second is None:
        return "UNAVAILABLE"
    return "MIXED"


def _extension_bucket(value: FeatureScalar) -> str:
    parsed = _numeric(value)
    if parsed is None:
        return "UNAVAILABLE"
    if parsed <= 0.03:
        return "AT_OR_NEAR_SUPPORT"
    if parsed <= 0.07:
        return "MODERATE"
    if parsed <= 0.10:
        return "EXTENDED"
    return "VERY_EXTENDED"


def _history_bucket(value: FeatureScalar) -> str:
    parsed = _numeric(value)
    if parsed is None:
        return "UNAVAILABLE"
    if parsed < 200:
        return "LT_200"
    if parsed < 500:
        return "200_499"
    if parsed < 1_000:
        return "500_999"
    return "GE_1000"


def _binary(value: bool | Decimal | None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value > 0
    return None


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


__all__ = ["ConditionalAttributionEngine"]
