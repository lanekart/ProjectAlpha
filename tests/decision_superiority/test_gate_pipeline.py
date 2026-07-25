from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.conclusions import (
    GateConclusion,
    GateRecommendation,
)
from alpha.decision_superiority.confidence import ConfidenceStatus
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineBatchResult,
    GatePipelineInput,
    GatePipelineResult,
    run_gate_pipeline,
    run_gate_pipeline_batch,
)
from alpha.decision_superiority.metrics import (
    EvidenceStrengthLevel,
    GateEconomicValue,
)
from alpha.decision_superiority.statistics import (
    build_distribution,
    build_evidence_strength,
)


def test_pipeline_builds_complete_gate_result() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="ENTRY_TIMING",
            sample_count=5,
            returns_pct=(
                Decimal("-5"),
                Decimal("-4"),
                Decimal("-3"),
                Decimal("-2"),
                Decimal("-1"),
            ),
            minimum_required=5,
        )
    )

    assert result.gate_code == "ENTRY_TIMING"
    assert result.distribution.sample_count == 5
    assert result.distribution.resolved_count == 5
    assert result.distribution.negative_count == 5
    assert result.evidence_strength.sufficient is True
    assert result.confidence.status is ConfidenceStatus.SUFFICIENT
    assert result.economic_value.net_gate_value == Decimal("15")
    assert result.conclusion.recommendation is GateRecommendation.RETAIN
    assert result.production_influence is False


def test_pipeline_exposes_metric_snapshot() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="WEAK_SETUP",
            sample_count=3,
            returns_pct=(
                Decimal("-2"),
                Decimal("1"),
            ),
            minimum_required=2,
        )
    )

    snapshot = result.metric_snapshot

    assert snapshot.gate_code == result.gate_code
    assert snapshot.distribution == result.distribution
    assert snapshot.evidence == result.evidence_strength
    assert snapshot.economic_value == result.economic_value


def test_pipeline_with_no_resolved_outcomes_fails_closed() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="NO_OUTCOMES",
            sample_count=10,
            returns_pct=(),
            minimum_required=5,
        )
    )

    assert result.distribution.resolved_count == 0
    assert result.confidence.status is ConfidenceStatus.UNAVAILABLE
    assert result.conclusion.recommendation is GateRecommendation.INSUFFICIENT_EVIDENCE
    assert result.conclusion.reason_code == "NO_RESOLVED_OUTCOMES"


def test_pipeline_below_minimum_is_insufficient() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="SMALL_SAMPLE",
            sample_count=10,
            returns_pct=(
                Decimal("-3"),
                Decimal("-2"),
            ),
            minimum_required=5,
        )
    )

    assert result.evidence_strength.sufficient is False
    assert result.confidence.status is ConfidenceStatus.INSUFFICIENT_SAMPLE
    assert result.conclusion.recommendation is GateRecommendation.INSUFFICIENT_EVIDENCE


def test_pipeline_can_recommend_remove() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="HARMFUL_GATE",
            sample_count=5,
            returns_pct=(
                Decimal("1"),
                Decimal("2"),
                Decimal("3"),
                Decimal("4"),
                Decimal("5"),
            ),
            minimum_required=5,
        )
    )

    assert result.economic_value.net_gate_value == Decimal("-15")
    assert result.conclusion.recommendation is GateRecommendation.REMOVE


def test_pipeline_can_recommend_review() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="MIXED_GATE",
            sample_count=4,
            returns_pct=(
                Decimal("-2"),
                Decimal("-1"),
                Decimal("1"),
                Decimal("2"),
            ),
            minimum_required=4,
        )
    )

    assert result.economic_value.net_gate_value == Decimal("0")
    assert result.conclusion.recommendation is GateRecommendation.REVIEW
    assert result.conclusion.reason_code == "ZERO_NET_GATE_VALUE"


def test_pipeline_is_deterministic() -> None:
    pipeline_input = GatePipelineInput(
        gate_code="DETERMINISTIC",
        sample_count=4,
        returns_pct=(
            Decimal("-4"),
            Decimal("-2"),
            Decimal("1"),
            Decimal("3"),
        ),
        minimum_required=4,
    )

    first = run_gate_pipeline(pipeline_input)
    second = run_gate_pipeline(pipeline_input)

    assert first == second


def test_pipeline_input_rejects_empty_gate_code() -> None:
    with pytest.raises(ValueError, match="gate_code cannot be empty"):
        GatePipelineInput(
            gate_code=" ",
            sample_count=0,
            returns_pct=(),
        )


def test_pipeline_input_rejects_negative_sample_count() -> None:
    with pytest.raises(ValueError, match="sample_count cannot be negative"):
        GatePipelineInput(
            gate_code="GATE",
            sample_count=-1,
            returns_pct=(),
        )


def test_pipeline_input_rejects_negative_minimum() -> None:
    with pytest.raises(ValueError, match="minimum_required cannot be negative"):
        GatePipelineInput(
            gate_code="GATE",
            sample_count=1,
            returns_pct=(),
            minimum_required=-1,
        )


def test_pipeline_input_rejects_excess_resolved_returns() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        GatePipelineInput(
            gate_code="GATE",
            sample_count=1,
            returns_pct=(
                Decimal("1"),
                Decimal("2"),
            ),
        )


def test_batch_orders_results_by_gate_code() -> None:
    result = run_gate_pipeline_batch(
        [
            GatePipelineInput(
                gate_code="GATE_C",
                sample_count=1,
                returns_pct=(Decimal("-1"),),
                minimum_required=1,
            ),
            GatePipelineInput(
                gate_code="GATE_A",
                sample_count=1,
                returns_pct=(Decimal("-1"),),
                minimum_required=1,
            ),
            GatePipelineInput(
                gate_code="GATE_B",
                sample_count=1,
                returns_pct=(Decimal("-1"),),
                minimum_required=1,
            ),
        ]
    )

    assert [row.gate_code for row in result.results] == [
        "GATE_A",
        "GATE_B",
        "GATE_C",
    ]


def test_batch_orders_conclusions_by_governed_recommendation() -> None:
    result = run_gate_pipeline_batch(
        [
            GatePipelineInput(
                gate_code="REMOVE_GATE",
                sample_count=3,
                returns_pct=(
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("3"),
                ),
                minimum_required=3,
            ),
            GatePipelineInput(
                gate_code="RETAIN_GATE",
                sample_count=3,
                returns_pct=(
                    Decimal("-1"),
                    Decimal("-2"),
                    Decimal("-3"),
                ),
                minimum_required=3,
            ),
            GatePipelineInput(
                gate_code="INSUFFICIENT_GATE",
                sample_count=3,
                returns_pct=(Decimal("-1"),),
                minimum_required=3,
            ),
        ]
    )

    assert [conclusion.recommendation for conclusion in result.conclusions] == [
        GateRecommendation.RETAIN,
        GateRecommendation.REMOVE,
        GateRecommendation.INSUFFICIENT_EVIDENCE,
    ]


def test_batch_rejects_duplicate_gate_codes() -> None:
    duplicate = GatePipelineInput(
        gate_code="DUPLICATE",
        sample_count=1,
        returns_pct=(Decimal("-1"),),
        minimum_required=1,
    )

    with pytest.raises(ValueError, match="gate_code values must be unique"):
        run_gate_pipeline_batch([duplicate, duplicate])


def test_batch_is_deterministic_across_input_order() -> None:
    gate_a = GatePipelineInput(
        gate_code="GATE_A",
        sample_count=2,
        returns_pct=(
            Decimal("-2"),
            Decimal("-1"),
        ),
        minimum_required=2,
    )
    gate_b = GatePipelineInput(
        gate_code="GATE_B",
        sample_count=2,
        returns_pct=(
            Decimal("1"),
            Decimal("2"),
        ),
        minimum_required=2,
    )

    forward = run_gate_pipeline_batch([gate_a, gate_b])
    reversed_result = run_gate_pipeline_batch([gate_b, gate_a])

    assert forward == reversed_result


def test_result_rejects_production_influence() -> None:
    distribution = build_distribution(
        sample_count=1,
        returns_pct=[Decimal("-1")],
    )
    evidence_strength = build_evidence_strength(
        sample_count=1,
        resolved_count=1,
        minimum_required=1,
    )
    economic_value = GateEconomicValue(
        profitable_rejection_cost=Decimal("0"),
        avoided_loss_benefit=Decimal("1"),
        net_gate_value=Decimal("1"),
    )
    valid = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE",
            sample_count=1,
            returns_pct=(Decimal("-1"),),
            minimum_required=1,
        )
    )

    with pytest.raises(ValueError, match="diagnostic-only"):
        GatePipelineResult(
            gate_code="GATE",
            distribution=distribution,
            evidence_strength=evidence_strength,
            economic_value=economic_value,
            confidence=valid.confidence,
            conclusion=valid.conclusion,
            production_influence=True,
        )


def test_result_rejects_mismatched_conclusion_gate_code() -> None:
    valid = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE",
            sample_count=1,
            returns_pct=(Decimal("-1"),),
            minimum_required=1,
        )
    )
    mismatched_conclusion = GateConclusion(
        gate_code="OTHER_GATE",
        economic_direction=valid.conclusion.economic_direction,
        statistical_direction=valid.conclusion.statistical_direction,
        recommendation=valid.conclusion.recommendation,
        reason_code=valid.conclusion.reason_code,
    )

    with pytest.raises(ValueError, match="must match pipeline gate_code"):
        GatePipelineResult(
            gate_code="GATE",
            distribution=valid.distribution,
            evidence_strength=valid.evidence_strength,
            economic_value=valid.economic_value,
            confidence=valid.confidence,
            conclusion=mismatched_conclusion,
        )


def test_batch_rejects_production_influence() -> None:
    valid = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE",
            sample_count=1,
            returns_pct=(Decimal("-1"),),
            minimum_required=1,
        )
    )

    with pytest.raises(ValueError, match="diagnostic-only"):
        GatePipelineBatchResult(
            results=(valid,),
            conclusions=(valid.conclusion,),
            production_influence=True,
        )


def test_pipeline_strength_matches_resolved_population() -> None:
    result = run_gate_pipeline(
        GatePipelineInput(
            gate_code="STRENGTH_GATE",
            sample_count=20,
            returns_pct=tuple(Decimal("-1") for _ in range(20)),
            minimum_required=20,
        )
    )

    assert result.evidence_strength.level is EvidenceStrengthLevel.MODERATE
    assert result.confidence.evidence_strength is EvidenceStrengthLevel.MODERATE
