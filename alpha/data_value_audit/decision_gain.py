"""Decision-quality impact assessment for DVRA candidates."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    ConfidenceLevel,
    DatasetCandidate,
    DecisionGainAssessment,
    ImpactLevel,
)

_POINTS = {
    ImpactLevel.HIGH: 100,
    ImpactLevel.MEDIUM: 60,
    ImpactLevel.LOW: 25,
    ImpactLevel.UNKNOWN: 0,
}


class DecisionGainEngine:
    """Score explicit decision dimensions without projecting realized performance."""

    def assess(self, candidate: DatasetCandidate) -> DecisionGainAssessment:
        known = tuple(
            item
            for item in candidate.decision_impacts
            if item.impact is not ImpactLevel.UNKNOWN
        )
        score = (
            round(sum(_POINTS[item.impact] for item in known) / len(known))
            if known
            else 0
        )
        primary = max(
            known,
            key=lambda item: (_POINTS[item.impact], item.dimension.value),
            default=None,
        )
        confidence = (
            ConfidenceLevel.INSUFFICIENT
            if not known
            else ConfidenceLevel.HIGH
            if len(known) >= 4
            else ConfidenceLevel.MEDIUM
            if len(known) >= 2
            else ConfidenceLevel.LOW
        )
        return DecisionGainAssessment(
            dataset_id=candidate.dataset_id,
            score=score,
            impacts=candidate.decision_impacts,
            confidence=confidence,
            primary_gain=(
                primary.dimension.value.replace("_", " ").title()
                if primary is not None
                else "Unknown"
            ),
        )


__all__ = ["DecisionGainEngine"]
