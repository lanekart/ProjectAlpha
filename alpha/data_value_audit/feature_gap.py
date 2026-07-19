"""Feature-gap attribution for candidate data assets."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    ConfidenceLevel,
    DatasetCandidate,
    FeatureGapAssessment,
    NoveltyClass,
)


class FeatureGapEngine:
    """Describe the current missing evidence and bounded expected resolution."""

    def assess(self, candidate: DatasetCandidate) -> FeatureGapAssessment:
        direct = candidate.novelty in {
            NoveltyClass.ADDS_NEW_FEATURE,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
        }
        return FeatureGapAssessment(
            dataset_id=candidate.dataset_id,
            gap=candidate.feature_gap,
            current_state="UNAVAILABLE_OR_PROVISIONAL",
            expected_resolution=(
                "Adds a directly testable point-in-time feature family."
                if direct
                else "Improves truth, continuity, or measurement of existing evidence."
            ),
            confidence=(ConfidenceLevel.HIGH if direct else ConfidenceLevel.MEDIUM),
        )


__all__ = ["FeatureGapEngine"]
