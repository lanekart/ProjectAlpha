from __future__ import annotations

from alpha.institutional_gate_truth.models import (
    HorizonOutcome,
    RejectionCandidate,
    RejectionClassification,
)


def classify_rejection(
    candidate: RejectionCandidate,
    outcome: HorizonOutcome,
) -> tuple[RejectionClassification, str]:
    """Classify the frozen rejection without tuning any decision threshold."""

    if not candidate.trade_plan_valid:
        return (
            RejectionClassification.DATA_UNCERTAIN,
            "The frozen trade plan lacks a valid entry, stop, or target.",
        )
    if not outcome.entered:
        if outcome.complete:
            return (
                RejectionClassification.MARGINAL,
                "The frozen entry trigger was not reached inside its validity window.",
            )
        return (
            RejectionClassification.DATA_UNCERTAIN,
            "The dataset ended before the entry-validity and holding window matured.",
        )
    if outcome.stop_before_target is True:
        return (
            RejectionClassification.CORRECT_REJECTION,
            "The prospective stop was reached before the prospective target.",
        )
    if outcome.target_reached is True:
        return (
            RejectionClassification.FALSE_REJECTION,
            "The prospective target was reached before the prospective stop.",
        )
    if not outcome.complete:
        return (
            RejectionClassification.DATA_UNCERTAIN,
            "The planned holding window is not fully observable and no "
            "terminal event occurred.",
        )
    if outcome.positive_after_costs is True:
        return (
            RejectionClassification.FALSE_REJECTION,
            "The planned time exit produced a positive return after frozen costs.",
        )
    if outcome.positive_after_costs is False and outcome.net_return_percent != 0:
        return (
            RejectionClassification.CORRECT_REJECTION,
            "The planned time exit produced a loss after frozen costs.",
        )
    return (
        RejectionClassification.MARGINAL,
        "The fully observed planned outcome was economically breakeven.",
    )


__all__ = ["classify_rejection"]
