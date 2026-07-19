from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from alpha.market_dna.models import (
    FeatureAudit,
    FeatureDefinition,
    FeatureKind,
    FeatureQuality,
    FeatureSnapshot,
)

_TWO = Decimal("0.01")


class FeatureQualityAuditEngine:
    """Audit availability, scale, point-in-time semantics, and quarantine state."""

    def audit(
        self,
        definitions: tuple[FeatureDefinition, ...],
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> tuple[FeatureAudit, ...]:
        return tuple(self._audit_one(item, snapshots) for item in definitions)

    def _audit_one(
        self,
        definition: FeatureDefinition,
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> FeatureAudit:
        values = tuple(
            item.feature_values.get(definition.feature_id, "unavailable")
            for item in snapshots
        )
        available = tuple(value for value in values if _available(value))
        missing = len(values) - len(available)
        missing_pct = _pct(missing, len(values)) or Decimal("0")
        scale_valid = all(_valid_scale(definition, value) for value in available)
        point_in_time_valid = all(
            item.feature_timestamp <= item.candidate_timestamp for item in snapshots
        )
        quality = definition.base_quality
        reasons = list(definition.known_defects)
        if quality not in {FeatureQuality.QUARANTINED, FeatureQuality.LEAKAGE_RISK}:
            if not point_in_time_valid:
                quality = FeatureQuality.LEAKAGE_RISK
                reasons.append("feature timestamp follows decision time")
            elif not scale_valid:
                quality = FeatureQuality.UNSTABLE
                reasons.append("observed values violate the declared scale")
            elif missing_pct > Decimal("40"):
                quality = FeatureQuality.INSUFFICIENT_COVERAGE
                reasons.append("missingness exceeds 40 percent")
        if definition.base_quality is FeatureQuality.USABLE_WITH_CAUTION:
            reasons.append("feature requires lineage or cross-sectional scale caution")
        return FeatureAudit(
            feature=replace(definition),
            quality=quality,
            population_count=len(values),
            available_count=len(available),
            missing_count=missing,
            missing_pct=missing_pct,
            distinct_values=len(set(available)),
            scale_valid=scale_valid,
            point_in_time_valid=point_in_time_valid,
            reasons=tuple(dict.fromkeys(reasons)),
        )


def numeric_value(snapshot: FeatureSnapshot, feature_id: str) -> Decimal | None:
    value = snapshot.feature_values.get(feature_id)
    if value is None or not _available(value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _valid_scale(definition: FeatureDefinition, value: str) -> bool:
    if definition.kind is FeatureKind.BOOLEAN:
        return value in {"true", "false"}
    if definition.kind is not FeatureKind.CONTINUOUS:
        return bool(value.strip())
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    if definition.valid_range == "0..100":
        return Decimal("0") <= number <= Decimal("100")
    if definition.valid_range == "0..1":
        return Decimal("0") <= number <= Decimal("1")
    if definition.valid_range == ">=0":
        return number >= Decimal("0")
    return True


def _available(value: str) -> bool:
    return bool(value.strip()) and value.strip().lower() not in {
        "unavailable",
        "none",
        "nan",
    }


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["FeatureQualityAuditEngine", "numeric_value"]
