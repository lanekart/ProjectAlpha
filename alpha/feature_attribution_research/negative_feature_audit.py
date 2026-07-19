"""Identify observable characteristics associated with failed opportunities."""

from __future__ import annotations

from decimal import Decimal

from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    EvidencePartition,
)


class NegativeFeatureAudit:
    def analyze(
        self, values: tuple[AttributionResult, ...]
    ) -> tuple[AttributionResult, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in values
                    if item.partition in {None, EvidencePartition.HOLDOUT}
                    and item.direction is AttributionDirection.NEGATIVE
                    and item.auc is not None
                ),
                key=lambda item: (
                    item.partition is EvidencePartition.HOLDOUT,
                    _auc_distance(item),
                    item.sample_count,
                    item.feature_id,
                ),
                reverse=True,
            )
        )


def _auc_distance(item: AttributionResult) -> Decimal:
    return Decimal("0") if item.auc is None else abs(item.auc - Decimal("0.5"))


__all__ = ["NegativeFeatureAudit"]
