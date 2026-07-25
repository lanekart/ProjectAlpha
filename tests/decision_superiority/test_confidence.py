from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.confidence import (
    ConfidenceStatus,
    DecimalInterval,
    assess_evidence,
    mean_confidence_interval,
    sample_variance,
    wilson_interval,
)
from alpha.decision_superiority.metrics import EvidenceStrengthLevel


def test_sample_variance_is_deterministic() -> None:
    result = sample_variance(
        (
            Decimal("1"),
            Decimal("2"),
            Decimal("3"),
        )
    )

    assert result == Decimal("1")


def test_sample_variance_empty_and_singleton_are_zero() -> None:
    assert sample_variance(()) == Decimal("0")
    assert sample_variance((Decimal("7"),)) == Decimal("0")


def test_wilson_interval_for_balanced_population() -> None:
    interval = wilson_interval(
        positive_count=5,
        resolved_count=10,
    )

    assert interval is not None
    assert interval.method == "WILSON_SCORE"
    assert interval.lower < Decimal("0.5")
    assert interval.upper > Decimal("0.5")
    assert Decimal("0") <= interval.lower <= interval.upper <= Decimal("1")


def test_wilson_interval_handles_zero_successes() -> None:
    interval = wilson_interval(
        positive_count=0,
        resolved_count=10,
    )

    assert interval is not None
    assert interval.lower == Decimal("0")
    assert interval.upper > Decimal("0")


def test_wilson_interval_handles_all_successes() -> None:
    interval = wilson_interval(
        positive_count=10,
        resolved_count=10,
    )

    assert interval is not None
    assert interval.upper == Decimal("1")
    assert interval.lower < Decimal("1")


def test_wilson_interval_empty_population_is_unavailable() -> None:
    assert wilson_interval(positive_count=0, resolved_count=0) is None


def test_wilson_interval_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        wilson_interval(
            positive_count=2,
            resolved_count=1,
        )


def test_mean_interval_contains_observed_mean() -> None:
    interval = mean_confidence_interval(
        mean=Decimal("4"),
        standard_deviation=Decimal("2"),
        resolved_count=25,
    )

    assert interval is not None
    assert interval.lower < Decimal("4")
    assert interval.upper > Decimal("4")
    assert interval.method == "NORMAL_APPROXIMATION"


def test_single_observation_mean_interval_is_degenerate() -> None:
    interval = mean_confidence_interval(
        mean=Decimal("6"),
        standard_deviation=Decimal("0"),
        resolved_count=1,
    )

    assert interval is not None
    assert interval.lower == Decimal("6")
    assert interval.upper == Decimal("6")
    assert interval.method == "SINGLE_OBSERVATION_DEGENERATE"


def test_assessment_with_no_resolved_outcomes_is_unavailable() -> None:
    result = assess_evidence(
        sample_count=10,
        returns_pct=[],
        minimum_required=5,
    )

    assert result.status is ConfidenceStatus.UNAVAILABLE
    assert result.insufficiency_reason == "NO_RESOLVED_OUTCOMES"
    assert result.success_rate is None
    assert result.success_rate_interval is None
    assert result.mean_return_interval is None
    assert result.evidence_strength is EvidenceStrengthLevel.VERY_LOW


def test_assessment_below_threshold_is_insufficient() -> None:
    result = assess_evidence(
        sample_count=10,
        returns_pct=[
            Decimal("5"),
            Decimal("-2"),
            Decimal("0"),
        ],
        minimum_required=5,
    )

    assert result.status is ConfidenceStatus.INSUFFICIENT_SAMPLE
    assert result.insufficiency_reason == "RESOLVED_OUTCOMES_BELOW_MINIMUM:3<5"
    assert result.positive_count == 1
    assert result.success_rate == Decimal("1") / Decimal("3")
    assert result.success_rate_interval is not None
    assert result.mean_return_interval is not None


def test_assessment_at_threshold_is_sufficient() -> None:
    result = assess_evidence(
        sample_count=5,
        returns_pct=[
            Decimal("5"),
            Decimal("-2"),
            Decimal("1"),
            Decimal("0"),
            Decimal("3"),
        ],
        minimum_required=5,
    )

    assert result.status is ConfidenceStatus.SUFFICIENT
    assert result.insufficiency_reason == ""
    assert result.resolved_count == 5


def test_assessment_calculates_dispersion() -> None:
    result = assess_evidence(
        sample_count=3,
        returns_pct=[
            Decimal("1"),
            Decimal("2"),
            Decimal("3"),
        ],
        minimum_required=1,
    )

    assert result.mean_return_pct == Decimal("2")
    assert result.variance_return_pct == Decimal("1")
    assert result.standard_deviation_return_pct == Decimal("1")


def test_assessment_rejects_more_resolved_than_sample_count() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        assess_evidence(
            sample_count=1,
            returns_pct=[Decimal("1"), Decimal("2")],
        )


def test_decimal_interval_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="lower bound"):
        DecimalInterval(
            lower=Decimal("2"),
            upper=Decimal("1"),
            confidence_level=Decimal("0.95"),
            method="TEST",
        )


def test_confidence_assessment_is_deterministic() -> None:
    returns = [
        Decimal("5"),
        Decimal("-2"),
        Decimal("1"),
        Decimal("0"),
    ]

    first = assess_evidence(
        sample_count=5,
        returns_pct=returns,
        minimum_required=3,
    )

    second = assess_evidence(
        sample_count=5,
        returns_pct=returns,
        minimum_required=3,
    )

    assert first == second
