from alpha.decision_superiority.confidence import (
    ConfidenceStatus,
    assess_evidence,
)


def test_empty_population_is_unavailable_when_minimum_is_zero() -> None:
    assessment = assess_evidence(
        sample_count=0,
        returns_pct=[],
        minimum_required=0,
    )

    assert assessment.status is ConfidenceStatus.UNAVAILABLE
    assert assessment.insufficiency_reason == "NO_RESOLVED_OUTCOMES"
    assert assessment.resolved_count == 0
    assert assessment.success_rate is None
    assert assessment.success_rate_interval is None
    assert assessment.mean_return_interval is None
