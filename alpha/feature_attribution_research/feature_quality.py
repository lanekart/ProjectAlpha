"""Feature completeness, distribution, and concentration diagnostics."""

from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal

import numpy as np

from alpha.feature_attribution_research.models import (
    EvidencePartition,
    FeatureDefinition,
    FeatureQualityFlag,
    FeatureQualityRecord,
    FeatureScalar,
    FeatureSnapshot,
)


class FeatureQualityEngine:
    def audit(
        self,
        *,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> tuple[FeatureQualityRecord, ...]:
        records = []
        population = len(snapshots)
        for definition in definitions:
            pairs = tuple(
                (item, _numeric(item.value(definition.feature_id)))
                for item in snapshots
            )
            available_pairs = tuple(
                (item, value) for item, value in pairs if value is not None
            )
            values = np.asarray([value for _, value in available_pairs], dtype=float)
            available = len(values)
            missing = population - available
            unique = len(set(float(item) for item in values))
            zero_variance = available > 0 and unique <= 1
            median = None if available == 0 else float(np.median(values))
            q1 = None if available == 0 else float(np.quantile(values, 0.25))
            q3 = None if available == 0 else float(np.quantile(values, 0.75))
            iqr = None if q1 is None or q3 is None else q3 - q1
            outlier_rate = _outlier_rate(values, q1, q3)
            coverage = {
                partition: _coverage(pairs, partition)
                for partition in EvidencePartition
            }
            flags: list[FeatureQualityFlag] = []
            missing_rate = _ratio(missing, population)
            if missing_rate >= Decimal("0.50"):
                flags.append(FeatureQualityFlag.HIGH_MISSINGNESS)
            if zero_variance:
                flags.append(FeatureQualityFlag.ZERO_VARIANCE)
            elif _near_constant(values):
                flags.append(FeatureQualityFlag.NEAR_CONSTANT)
            if outlier_rate is not None and outlier_rate >= Decimal("0.10"):
                flags.append(FeatureQualityFlag.OUTLIER_DOMINATED)
            if max(coverage.values(), default=Decimal("0")) - min(
                coverage.values(), default=Decimal("0")
            ) >= Decimal("0.20"):
                flags.append(FeatureQualityFlag.PARTITION_DRIFT)
            if _era_drift(available_pairs, iqr):
                flags.append(FeatureQualityFlag.ERA_DRIFT)
            if _symbol_concentrated(available_pairs):
                flags.append(FeatureQualityFlag.SYMBOL_CONCENTRATION)
            if not definition.point_in_time_safe:
                flags.append(FeatureQualityFlag.DATA_NOT_POINT_IN_TIME)
            if not flags:
                flags.append(FeatureQualityFlag.PASS)
            records.append(
                FeatureQualityRecord(
                    feature_id=definition.feature_id,
                    population_count=population,
                    available_count=available,
                    missing_count=missing,
                    missing_rate=missing_rate,
                    unique_values=unique,
                    zero_variance=zero_variance,
                    outlier_rate=outlier_rate,
                    minimum=_decimal(float(np.min(values))) if available else None,
                    maximum=_decimal(float(np.max(values))) if available else None,
                    median=_optional_decimal(median),
                    iqr=_optional_decimal(iqr),
                    development_coverage=coverage[EvidencePartition.DEVELOPMENT],
                    validation_coverage=coverage[EvidencePartition.VALIDATION],
                    holdout_coverage=coverage[EvidencePartition.HOLDOUT],
                    flags=tuple(flags),
                )
            )
        return tuple(records)


def _coverage(
    pairs: tuple[tuple[FeatureSnapshot, float | None], ...],
    partition: EvidencePartition,
) -> Decimal:
    subset = tuple(item for item in pairs if item[0].partition is partition)
    available = sum(value is not None for _, value in subset)
    return _ratio(available, len(subset))


def _outlier_rate(
    values: np.ndarray[tuple[int], np.dtype[np.float64]],
    q1: float | None,
    q3: float | None,
) -> Decimal | None:
    if values.size == 0 or q1 is None or q3 is None:
        return None
    spread = q3 - q1
    if spread <= 0:
        return Decimal("0")
    outliers = np.sum((values < q1 - 3 * spread) | (values > q3 + 3 * spread))
    return _ratio(int(outliers), int(values.size))


def _near_constant(values: np.ndarray[tuple[int], np.dtype[np.float64]]) -> bool:
    if values.size < 20:
        return False
    rounded = Counter(round(float(item), 8) for item in values)
    return rounded.most_common(1)[0][1] / values.size >= 0.98


def _era_drift(
    pairs: tuple[tuple[FeatureSnapshot, float], ...], iqr: float | None
) -> bool:
    if len(pairs) < 100 or iqr is None or iqr <= 0:
        return False
    years = sorted({item.onset_date.year for item, _ in pairs})
    if len(years) < 2:
        return False
    first = [value for item, value in pairs if item.onset_date.year == years[0]]
    last = [value for item, value in pairs if item.onset_date.year == years[-1]]
    if len(first) < 20 or len(last) < 20:
        return False
    return abs(float(np.median(first)) - float(np.median(last))) > 2 * iqr


def _symbol_concentrated(pairs: tuple[tuple[FeatureSnapshot, float], ...]) -> bool:
    if not pairs:
        return False
    counts = Counter(item.symbol for item, _ in pairs)
    return counts.most_common(1)[0][1] / len(pairs) > 0.10


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (
        Decimal("0") if denominator == 0 else Decimal(numerator) / Decimal(denominator)
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None else _decimal(value)


__all__ = ["FeatureQualityEngine"]
