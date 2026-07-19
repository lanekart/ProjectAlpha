from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.institutional_gate_truth.models import (
    ComponentAttribution,
    RejectionAssessment,
    RejectionClassification,
)
from alpha.institutional_gate_truth.rejection_statistics import rate


def false_rejections(
    assessments: tuple[RejectionAssessment, ...],
) -> tuple[RejectionAssessment, ...]:
    return tuple(
        item
        for item in assessments
        if item.classification is RejectionClassification.FALSE_REJECTION
    )


def component_attribution(
    assessments: tuple[RejectionAssessment, ...],
) -> tuple[ComponentAttribution, ...]:
    false = false_rejections(assessments)
    counts = Counter(item.primary_component for item in false)
    return tuple(
        ComponentAttribution(
            component=component,
            false_rejections=count,
            false_rejection_share_percent=rate(count, len(false)),
        )
        for component, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    )


def missed_return_total(
    assessments: tuple[RejectionAssessment, ...],
) -> Decimal:
    return sum(
        (
            item.planned_outcome.net_return_percent
            for item in false_rejections(assessments)
            if item.planned_outcome.net_return_percent is not None
            and item.planned_outcome.net_return_percent > 0
        ),
        start=Decimal("0"),
    )


__all__ = ["component_attribution", "false_rejections", "missed_return_total"]
