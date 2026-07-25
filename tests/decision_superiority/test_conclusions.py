from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.conclusions import (
    EconomicDirection,
    GateConclusion,
    GateRecommendation,
    StatisticalDirection,
    classify_economic_direction,
    classify_statistical_direction,
    conclude_gate,
    rank_conclusions,
)
from alpha.decision_superiority.confidence import assess_evidence
from alpha.decision_superiority.metrics import GateEconomicValue


def _value(*, avoided: str, cost: str) -> GateEconomicValue:
    avoided_value = Decimal(avoided)
    cost_value = Decimal(cost)
    return GateEconomicValue(
        profitable_rejection_cost=cost_value,
        avoided_loss_benefit=avoided_value,
        net_gate_value=avoided_value - cost_value,
    )


def test_economic_direction_classifies_all_signs() -> None:
    assert (
        classify_economic_direction(_value(avoided="5", cost="1"))
        is EconomicDirection.POSITIVE
    )
    assert (
        classify_economic_direction(_value(avoided="1", cost="5"))
        is EconomicDirection.NEGATIVE
    )
    assert (
        classify_economic_direction(_value(avoided="2", cost="2"))
        is EconomicDirection.NEUTRAL
    )


def test_statistical_direction_negative() -> None:
    evidence = assess_evidence(
        sample_count=20,
        returns_pct=[Decimal("-5")] * 20,
        minimum_required=20,
    )

    assert classify_statistical_direction(evidence) is StatisticalDirection.NEGATIVE


def test_statistical_direction_positive() -> None:
    evidence = assess_evidence(
        sample_count=20,
        returns_pct=[Decimal("5")] * 20,
        minimum_required=20,
    )

    assert classify_statistical_direction(evidence) is StatisticalDirection.POSITIVE


def test_statistical_direction_inconclusive() -> None:
    evidence = assess_evidence(
        sample_count=20,
        returns_pct=[Decimal("-1"), Decimal("1")] * 10,
        minimum_required=20,
    )

    assert classify_statistical_direction(evidence) is StatisticalDirection.INCONCLUSIVE


def test_statistical_direction_unavailable() -> None:
    evidence = assess_evidence(
        sample_count=20,
        returns_pct=[],
        minimum_required=20,
    )

    assert classify_statistical_direction(evidence) is StatisticalDirection.UNAVAILABLE


def test_positive_value_and_negative_rejected_returns_retain_gate() -> None:
    conclusion = conclude_gate(
        gate_code="RISK_GATE",
        economic_value=_value(avoided="100", cost="10"),
        evidence=assess_evidence(
            sample_count=20,
            returns_pct=[Decimal("-5")] * 20,
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.RETAIN
    assert conclusion.reason_code == ("POSITIVE_NET_VALUE_AND_NEGATIVE_REJECTED_RETURN")
    assert conclusion.production_influence is False


def test_negative_value_and_positive_rejected_returns_remove_gate() -> None:
    conclusion = conclude_gate(
        gate_code="ENTRY_GATE",
        economic_value=_value(avoided="10", cost="100"),
        evidence=assess_evidence(
            sample_count=20,
            returns_pct=[Decimal("5")] * 20,
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.REMOVE
    assert conclusion.reason_code == ("NEGATIVE_NET_VALUE_AND_POSITIVE_REJECTED_RETURN")


def test_insufficient_population_blocks_economic_recommendation() -> None:
    conclusion = conclude_gate(
        gate_code="SETUP_GATE",
        economic_value=_value(avoided="100", cost="0"),
        evidence=assess_evidence(
            sample_count=2,
            returns_pct=[Decimal("-5"), Decimal("-4")],
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.INSUFFICIENT_EVIDENCE
    assert conclusion.reason_code == "RESOLVED_OUTCOMES_BELOW_MINIMUM:2<20"


def test_no_resolved_population_is_insufficient() -> None:
    conclusion = conclude_gate(
        gate_code="QUALITY_GATE",
        economic_value=_value(avoided="0", cost="0"),
        evidence=assess_evidence(
            sample_count=10,
            returns_pct=[],
            minimum_required=5,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.INSUFFICIENT_EVIDENCE
    assert conclusion.statistical_direction is StatisticalDirection.UNAVAILABLE
    assert conclusion.reason_code == "NO_RESOLVED_OUTCOMES"


def test_zero_net_value_requires_review() -> None:
    conclusion = conclude_gate(
        gate_code="NEUTRAL_GATE",
        economic_value=_value(avoided="10", cost="10"),
        evidence=assess_evidence(
            sample_count=20,
            returns_pct=[Decimal("-5")] * 20,
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.REVIEW
    assert conclusion.reason_code == "ZERO_NET_GATE_VALUE"


def test_interval_crossing_zero_requires_review() -> None:
    conclusion = conclude_gate(
        gate_code="UNCERTAIN_GATE",
        economic_value=_value(avoided="20", cost="10"),
        evidence=assess_evidence(
            sample_count=20,
            returns_pct=[Decimal("-1"), Decimal("1")] * 10,
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.REVIEW
    assert conclusion.reason_code == "MEAN_RETURN_INTERVAL_CROSSES_ZERO"


def test_conflicting_signals_require_review() -> None:
    conclusion = conclude_gate(
        gate_code="CONFLICT_GATE",
        economic_value=_value(avoided="100", cost="10"),
        evidence=assess_evidence(
            sample_count=20,
            returns_pct=[Decimal("5")] * 20,
            minimum_required=20,
        ),
    )

    assert conclusion.recommendation is GateRecommendation.REVIEW
    assert conclusion.reason_code == "ECONOMIC_AND_STATISTICAL_SIGNALS_CONFLICT"


def test_conclusion_rejects_production_influence() -> None:
    with pytest.raises(ValueError, match="diagnostic-only"):
        GateConclusion(
            gate_code="RISK_GATE",
            economic_direction=EconomicDirection.POSITIVE,
            statistical_direction=StatisticalDirection.NEGATIVE,
            recommendation=GateRecommendation.RETAIN,
            reason_code="TEST",
            production_influence=True,
        )


def test_conclusion_rejects_empty_gate_code() -> None:
    with pytest.raises(ValueError, match="gate_code"):
        GateConclusion(
            gate_code=" ",
            economic_direction=EconomicDirection.POSITIVE,
            statistical_direction=StatisticalDirection.NEGATIVE,
            recommendation=GateRecommendation.RETAIN,
            reason_code="TEST",
        )


def test_ranking_is_recommendation_then_gate_code() -> None:
    conclusions = [
        GateConclusion(
            gate_code="GATE_Z",
            economic_direction=EconomicDirection.NEGATIVE,
            statistical_direction=StatisticalDirection.POSITIVE,
            recommendation=GateRecommendation.REMOVE,
            reason_code="REMOVE",
        ),
        GateConclusion(
            gate_code="GATE_B",
            economic_direction=EconomicDirection.POSITIVE,
            statistical_direction=StatisticalDirection.NEGATIVE,
            recommendation=GateRecommendation.RETAIN,
            reason_code="RETAIN",
        ),
        GateConclusion(
            gate_code="GATE_A",
            economic_direction=EconomicDirection.POSITIVE,
            statistical_direction=StatisticalDirection.NEGATIVE,
            recommendation=GateRecommendation.RETAIN,
            reason_code="RETAIN",
        ),
        GateConclusion(
            gate_code="GATE_I",
            economic_direction=EconomicDirection.NEUTRAL,
            statistical_direction=StatisticalDirection.UNAVAILABLE,
            recommendation=GateRecommendation.INSUFFICIENT_EVIDENCE,
            reason_code="NO_RESOLVED_OUTCOMES",
        ),
    ]

    ranked = rank_conclusions(conclusions)

    assert [row.gate_code for row in ranked] == [
        "GATE_A",
        "GATE_B",
        "GATE_Z",
        "GATE_I",
    ]


def test_conclusion_is_deterministic() -> None:
    evidence = assess_evidence(
        sample_count=20,
        returns_pct=[Decimal("-5")] * 20,
        minimum_required=20,
    )
    economic_value = _value(avoided="100", cost="10")

    first = conclude_gate(
        gate_code="RISK_GATE",
        economic_value=economic_value,
        evidence=evidence,
    )
    second = conclude_gate(
        gate_code="RISK_GATE",
        economic_value=economic_value,
        evidence=evidence,
    )

    assert first == second
