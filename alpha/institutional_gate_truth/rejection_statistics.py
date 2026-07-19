from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from alpha.institutional_gate_truth.models import (
    RejectionAssessment,
    RejectionClassification,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def classification_counts(
    assessments: tuple[RejectionAssessment, ...],
) -> Counter[RejectionClassification]:
    return Counter(item.classification for item in assessments)


def rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def average_return(
    assessments: tuple[RejectionAssessment, ...],
) -> Decimal | None:
    values = tuple(
        value
        for item in assessments
        if (value := item.planned_outcome.net_return_percent) is not None
    )
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["average_return", "classification_counts", "rate"]
