from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.metrics import (
    EconomicDistribution,
    EvidenceStrength,
    EvidenceStrengthLevel,
    GateEconomicValue,
    GateMetricSnapshot,
)


def _distribution() -> EconomicDistribution:
    return EconomicDistribution(
        sample_count=5,
        resolved_count=3,
        positive_count=1,
        negative_count=1,
        flat_count=1,
        mean_return_pct=Decimal("1"),
        median_return_pct=Decimal("0"),
        best_return_pct=Decimal("5"),
        worst_return_pct=Decimal("-2"),
    )


def _evidence() -> EvidenceStrength:
    return EvidenceStrength(
        sample_count=5,
        resolved_count=3,
        minimum_required=3,
        level=EvidenceStrengthLevel.MODERATE,
        sufficient=True,
    )


def _economic_value() -> GateEconomicValue:
    return GateEconomicValue(
        profitable_rejection_cost=Decimal("5"),
        avoided_loss_benefit=Decimal("8"),
        net_gate_value=Decimal("3"),
    )


def test_metric_snapshot_is_immutable_and_consistent() -> None:
    snapshot = GateMetricSnapshot(
        gate_code="GATE_A",
        distribution=_distribution(),
        evidence=_evidence(),
        economic_value=_economic_value(),
    )

    assert snapshot.gate_code == "GATE_A"
    assert snapshot.economic_value.net_gate_value == Decimal("3")

    with pytest.raises(AttributeError):
        snapshot.gate_code = "GATE_B"  # type: ignore[misc]


def test_distribution_requires_resolved_classification_identity() -> None:
    with pytest.raises(
        ValueError,
        match="must equal resolved_count",
    ):
        EconomicDistribution(
            sample_count=5,
            resolved_count=3,
            positive_count=1,
            negative_count=1,
            flat_count=0,
            mean_return_pct=Decimal("1"),
            median_return_pct=Decimal("0"),
            best_return_pct=Decimal("5"),
            worst_return_pct=Decimal("-2"),
        )


def test_empty_distribution_requires_zero_metrics() -> None:
    with pytest.raises(
        ValueError,
        match="zero-valued metrics",
    ):
        EconomicDistribution(
            sample_count=2,
            resolved_count=0,
            positive_count=0,
            negative_count=0,
            flat_count=0,
            mean_return_pct=Decimal("1"),
            median_return_pct=Decimal("0"),
            best_return_pct=Decimal("0"),
            worst_return_pct=Decimal("0"),
        )


def test_distribution_rejects_inverted_best_and_worst() -> None:
    with pytest.raises(
        ValueError,
        match="best_return_pct",
    ):
        EconomicDistribution(
            sample_count=2,
            resolved_count=2,
            positive_count=1,
            negative_count=1,
            flat_count=0,
            mean_return_pct=Decimal("0"),
            median_return_pct=Decimal("0"),
            best_return_pct=Decimal("-2"),
            worst_return_pct=Decimal("4"),
        )


def test_evidence_sufficiency_must_match_threshold() -> None:
    with pytest.raises(
        ValueError,
        match="sufficient",
    ):
        EvidenceStrength(
            sample_count=10,
            resolved_count=2,
            minimum_required=3,
            level=EvidenceStrengthLevel.LOW,
            sufficient=True,
        )


def test_gate_economic_value_enforces_accounting_identity() -> None:
    with pytest.raises(
        ValueError,
        match="must equal",
    ):
        GateEconomicValue(
            profitable_rejection_cost=Decimal("5"),
            avoided_loss_benefit=Decimal("8"),
            net_gate_value=Decimal("4"),
        )


def test_gate_economic_value_rejects_negative_components() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        GateEconomicValue(
            profitable_rejection_cost=Decimal("-1"),
            avoided_loss_benefit=Decimal("0"),
            net_gate_value=Decimal("1"),
        )


def test_snapshot_requires_matching_population_counts() -> None:
    evidence = EvidenceStrength(
        sample_count=6,
        resolved_count=3,
        minimum_required=3,
        level=EvidenceStrengthLevel.MODERATE,
        sufficient=True,
    )

    with pytest.raises(
        ValueError,
        match="sample_count",
    ):
        GateMetricSnapshot(
            gate_code="GATE_A",
            distribution=_distribution(),
            evidence=evidence,
            economic_value=_economic_value(),
        )


def test_snapshot_rejects_empty_gate_code() -> None:
    with pytest.raises(ValueError, match="gate_code"):
        GateMetricSnapshot(
            gate_code=" ",
            distribution=_distribution(),
            evidence=_evidence(),
            economic_value=_economic_value(),
        )
