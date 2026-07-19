"""Categorical replay-impact assessment without fabricated performance values."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    ConfidenceLevel,
    DatasetCandidate,
    ImpactLevel,
    ReplayGainAssessment,
    ReplayImpact,
    ReplayMetric,
)

_ORDER = {
    ImpactLevel.UNKNOWN: 0,
    ImpactLevel.LOW: 1,
    ImpactLevel.MEDIUM: 2,
    ImpactLevel.HIGH: 3,
}


class ReplayGainEngine:
    """Summarize per-metric replay influence as HIGH/MEDIUM/LOW/UNKNOWN."""

    def assess(self, candidate: DatasetCandidate) -> ReplayGainAssessment:
        recorded = {item.metric: item for item in candidate.replay_impacts}
        complete_impacts = tuple(
            recorded.get(
                metric,
                ReplayImpact(
                    metric=metric,
                    impact=ImpactLevel.UNKNOWN,
                    reason=(
                        f"{candidate.name} has no evidence-backed {metric.value} "
                        "impact estimate; the effect remains unknown."
                    ),
                ),
            )
            for metric in ReplayMetric
        )
        known = tuple(
            item for item in complete_impacts if item.impact is not ImpactLevel.UNKNOWN
        )
        overall = (
            max((item.impact for item in known), key=_ORDER.__getitem__)
            if known
            else ImpactLevel.UNKNOWN
        )
        confidence = (
            ConfidenceLevel.INSUFFICIENT
            if not known
            else ConfidenceLevel.HIGH
            if len(known) >= 4
            and any(item.impact is ImpactLevel.HIGH for item in known)
            else ConfidenceLevel.MEDIUM
        )
        return ReplayGainAssessment(
            dataset_id=candidate.dataset_id,
            overall=overall,
            impacts=complete_impacts,
            confidence=confidence,
        )


__all__ = ["ReplayGainEngine"]
