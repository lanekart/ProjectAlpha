"""Cross-subsystem leverage assessment for candidate datasets."""

from __future__ import annotations

from alpha.data_value_audit.models import (
    DatasetCandidate,
    InfrastructureGainAssessment,
    Subsystem,
)

_CRITICAL = {
    Subsystem.REPLAY,
    Subsystem.POINT_IN_TIME_UNIVERSE,
    Subsystem.FEATURE_ATTRIBUTION,
    Subsystem.GATE_TRUTH,
    Subsystem.MARKET_OPPORTUNITY,
}


class InfrastructureGainEngine:
    """Measure breadth and criticality of subsystem reuse."""

    def assess(self, candidate: DatasetCandidate) -> InfrastructureGainAssessment:
        unique = tuple(dict.fromkeys(candidate.subsystems))
        critical_count = sum(item in _CRITICAL for item in unique)
        score = min(100, len(unique) * 8 + critical_count * 7)
        primary_unlock = (
            candidate.unlocks[0]
            if candidate.unlocks
            else unique[0].value.lower()
            if unique
            else "unknown"
        )
        return InfrastructureGainAssessment(
            dataset_id=candidate.dataset_id,
            score=score,
            subsystem_count=len(unique),
            subsystems=unique,
            primary_unlock=primary_unlock,
        )


__all__ = ["InfrastructureGainEngine"]
