"""Evidence-grounded information-gain rubric for DVRA candidates."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    ConfidenceLevel,
    DatasetCandidate,
    ImpactLevel,
    InformationGainAssessment,
    NoveltyClass,
)

_NOVELTY_POINTS = {
    NoveltyClass.RECONCILES_CORE_TRUTH: 30,
    NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT: 25,
    NoveltyClass.ADDS_NEW_FEATURE: 20,
    NoveltyClass.REFINES_EXISTING_FEATURE: 12,
    NoveltyClass.MOSTLY_DUPLICATIVE: 5,
}
_BIAS_POINTS = {
    ImpactLevel.HIGH: 25,
    ImpactLevel.MEDIUM: 16,
    ImpactLevel.LOW: 6,
    ImpactLevel.UNKNOWN: 0,
}
_AUTHORITY_POINTS = {
    ImpactLevel.HIGH: 20,
    ImpactLevel.MEDIUM: 12,
    ImpactLevel.LOW: 5,
    ImpactLevel.UNKNOWN: 0,
}
_POINT_IN_TIME_POINTS = {
    ImpactLevel.HIGH: 15,
    ImpactLevel.MEDIUM: 9,
    ImpactLevel.LOW: 3,
    ImpactLevel.UNKNOWN: 0,
}


class InformationGainEngine:
    """Convert documented evidence properties into a transparent 0-100 score."""

    def assess(self, candidate: DatasetCandidate) -> InformationGainAssessment:
        novelty = _NOVELTY_POINTS[candidate.novelty]
        bias = _BIAS_POINTS[candidate.bias_control]
        authority = _AUTHORITY_POINTS[candidate.authority]
        point_in_time = _POINT_IN_TIME_POINTS[candidate.point_in_time_value]
        evidence = min(10, len(set(candidate.evidence_sources)) * 2)
        score = novelty + bias + authority + point_in_time + evidence
        confidence = _confidence(candidate, evidence)
        return InformationGainAssessment(
            dataset_id=candidate.dataset_id,
            score=score,
            novelty_points=novelty,
            bias_control_points=bias,
            authority_points=authority,
            point_in_time_points=point_in_time,
            evidence_points=evidence,
            confidence=confidence,
            rationale=(
                "Ordinal evidence rubric: novelty 30%, bias control 25%, source "
                "authority 20%, point-in-time value 15%, and cited audit coverage "
                "10%. It estimates information value, not financial return."
            ),
        )


def _confidence(candidate: DatasetCandidate, evidence_points: int) -> ConfidenceLevel:
    if candidate.authority is ImpactLevel.UNKNOWN or evidence_points < 4:
        return ConfidenceLevel.INSUFFICIENT
    if candidate.authority is ImpactLevel.LOW:
        return ConfidenceLevel.LOW
    if candidate.authority is ImpactLevel.HIGH and evidence_points >= 8:
        return ConfidenceLevel.HIGH
    return ConfidenceLevel.MEDIUM


__all__ = ["InformationGainEngine"]
