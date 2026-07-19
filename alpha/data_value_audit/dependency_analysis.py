"""Deterministic dependency and sensitivity analysis for DVRA."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    ConfidenceLevel,
    DatasetCandidate,
    DatasetReportCard,
    DependencyEdge,
    SensitivityAssessment,
)


class DependencyAnalysisEngine:
    """Build unlock edges and report value lost when a major dataset is unavailable."""

    def edges(
        self, candidates: tuple[DatasetCandidate, ...]
    ) -> tuple[DependencyEdge, ...]:
        rows: list[DependencyEdge] = []
        for candidate in candidates:
            rows.extend(
                DependencyEdge(dependency, candidate.dataset_id, "REQUIRED_BY")
                for dependency in candidate.dependencies
            )
            rows.extend(
                DependencyEdge(candidate.dataset_id, unlock, "UNLOCKS")
                for unlock in candidate.unlocks
            )
        return tuple(
            sorted(
                set(rows),
                key=lambda item: (
                    item.source_dataset_id,
                    item.relationship,
                    item.target,
                ),
            )
        )

    def sensitivity(
        self,
        cards: tuple[DatasetReportCard, ...],
    ) -> tuple[SensitivityAssessment, ...]:
        rows = []
        for card in cards:
            candidate = card.candidate
            dependents = sum(
                candidate.dataset_id in other.candidate.dependencies for other in cards
            )
            unlock_count = len(candidate.unlocks) + dependents
            rows.append(
                SensitivityAssessment(
                    dataset_id=candidate.dataset_id,
                    unavailable_effect=(
                        f"Lose {unlock_count} direct unlock/dependency paths "
                        "and retain "
                        f"the documented gap: {candidate.feature_gap}"
                    ),
                    dependent_unlocks_lost=unlock_count,
                    value_score_lost=card.gross_value_score,
                    confidence=(
                        ConfidenceLevel.HIGH
                        if unlock_count >= 4
                        else ConfidenceLevel.MEDIUM
                    ),
                )
            )
        return tuple(
            sorted(
                rows, key=lambda item: (-item.dependent_unlocks_lost, item.dataset_id)
            )
        )


__all__ = ["DependencyAnalysisEngine"]
