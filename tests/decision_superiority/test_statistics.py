from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.metrics import EvidenceStrengthLevel
from alpha.decision_superiority.statistics import (
    build_distribution,
    build_evidence_strength,
    build_gate_value,
    evidence_strength_level,
    rank_gate_snapshots,
)


def test_distribution_calculates_mean() -> None:
    result = build_distribution(
        sample_count=2,
        returns_pct=[Decimal("-5"), Decimal("5")],
    )

    assert result.mean_return_pct == Decimal("0")


def test_distribution_calculates_odd_median() -> None:
    result = build_distribution(
        sample_count=3,
        returns_pct=[
            Decimal("7"),
            Decimal("-10"),
            Decimal("-1"),
        ],
    )

    assert result.median_return_pct == Decimal("-1")


def test_distribution_calculates_even_median() -> None:
    result = build_distribution(
        sample_count=4,
        returns_pct=[
            Decimal("-10"),
            Decimal("-2"),
            Decimal("2"),
            Decimal("10"),
        ],
    )

    assert result.median_return_pct == Decimal("0")


def test_distribution_calculates_best_and_worst_returns() -> None:
    result = build_distribution(
        sample_count=4,
        returns_pct=[
            Decimal("-18"),
            Decimal("12"),
            Decimal("3"),
            Decimal("0"),
        ],
    )

    assert result.best_return_pct == Decimal("12")
    assert result.worst_return_pct == Decimal("-18")


def test_empty_distribution_uses_zero_metrics() -> None:
    result = build_distribution(
        sample_count=5,
        returns_pct=[],
    )

    assert result.sample_count == 5
    assert result.resolved_count == 0
    assert result.positive_count == 0
    assert result.negative_count == 0
    assert result.flat_count == 0
    assert result.mean_return_pct == Decimal("0")
    assert result.median_return_pct == Decimal("0")
    assert result.best_return_pct == Decimal("0")
    assert result.worst_return_pct == Decimal("0")


def test_distribution_classifies_positive_negative_and_flat() -> None:
    result = build_distribution(
        sample_count=5,
        returns_pct=[
            Decimal("5"),
            Decimal("1"),
            Decimal("-3"),
            Decimal("0"),
        ],
    )

    assert result.resolved_count == 4
    assert result.positive_count == 2
    assert result.negative_count == 1
    assert result.flat_count == 1
    assert (
        result.positive_count + result.negative_count + result.flat_count
        == result.resolved_count
    )


def test_distribution_rejects_more_resolved_returns_than_sample_count() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed sample_count",
    ):
        build_distribution(
            sample_count=1,
            returns_pct=[Decimal("1"), Decimal("2")],
        )


def test_gate_value_calculates_economic_accounting() -> None:
    result = build_gate_value(
        returns_pct=[
            Decimal("8"),
            Decimal("2"),
            Decimal("-5"),
            Decimal("-3"),
            Decimal("0"),
        ]
    )

    assert result.profitable_rejection_cost == Decimal("10")
    assert result.avoided_loss_benefit == Decimal("8")
    assert result.net_gate_value == Decimal("-2")


def test_gate_value_empty_population_is_zero() -> None:
    result = build_gate_value(returns_pct=[])

    assert result.profitable_rejection_cost == Decimal("0")
    assert result.avoided_loss_benefit == Decimal("0")
    assert result.net_gate_value == Decimal("0")


@pytest.mark.parametrize(
    ("resolved_count", "expected"),
    [
        (0, EvidenceStrengthLevel.VERY_LOW),
        (9, EvidenceStrengthLevel.VERY_LOW),
        (10, EvidenceStrengthLevel.LOW),
        (19, EvidenceStrengthLevel.LOW),
        (20, EvidenceStrengthLevel.MODERATE),
        (49, EvidenceStrengthLevel.MODERATE),
        (50, EvidenceStrengthLevel.HIGH),
        (99, EvidenceStrengthLevel.HIGH),
        (100, EvidenceStrengthLevel.VERY_HIGH),
    ],
)
def test_evidence_strength_level_boundaries(
    resolved_count: int,
    expected: EvidenceStrengthLevel,
) -> None:
    assert evidence_strength_level(resolved_count) is expected


def test_build_evidence_strength_tracks_sufficiency_separately_from_level() -> None:
    result = build_evidence_strength(
        sample_count=25,
        resolved_count=12,
        minimum_required=20,
    )

    assert result.level is EvidenceStrengthLevel.LOW
    assert result.sufficient is False
    assert result.minimum_required == 20


def test_build_evidence_strength_marks_threshold_as_sufficient() -> None:
    result = build_evidence_strength(
        sample_count=25,
        resolved_count=20,
        minimum_required=20,
    )

    assert result.level is EvidenceStrengthLevel.MODERATE
    assert result.sufficient is True


def test_gate_ranking_is_net_value_then_evidence_then_gate_code() -> None:
    value_a = build_gate_value(returns_pct=[Decimal("-5"), Decimal("1")])
    value_b = build_gate_value(returns_pct=[Decimal("-4")])
    value_c = build_gate_value(returns_pct=[Decimal("-4")])

    evidence_a = build_evidence_strength(
        sample_count=2,
        resolved_count=2,
        minimum_required=1,
    )
    evidence_b = build_evidence_strength(
        sample_count=3,
        resolved_count=3,
        minimum_required=1,
    )
    evidence_c = build_evidence_strength(
        sample_count=2,
        resolved_count=2,
        minimum_required=1,
    )

    ranked = rank_gate_snapshots(
        [
            ("GATE_C", value_c, evidence_c),
            ("GATE_A", value_a, evidence_a),
            ("GATE_B", value_b, evidence_b),
        ]
    )

    assert [row[0] for row in ranked] == [
        "GATE_B",
        "GATE_A",
        "GATE_C",
    ]


def test_gate_ranking_is_deterministic_for_identical_metrics() -> None:
    value = build_gate_value(returns_pct=[Decimal("-2")])
    evidence = build_evidence_strength(
        sample_count=1,
        resolved_count=1,
        minimum_required=1,
    )

    first = rank_gate_snapshots(
        [
            ("GATE_B", value, evidence),
            ("GATE_A", value, evidence),
        ]
    )
    second = rank_gate_snapshots(
        [
            ("GATE_A", value, evidence),
            ("GATE_B", value, evidence),
        ]
    )

    assert first == second
    assert [row[0] for row in first] == ["GATE_A", "GATE_B"]


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        evidence_strength_level(-1)

    with pytest.raises(ValueError, match="cannot be negative"):
        build_evidence_strength(
            sample_count=1,
            resolved_count=-1,
            minimum_required=1,
        )
