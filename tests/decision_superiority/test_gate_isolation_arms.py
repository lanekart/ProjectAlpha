from __future__ import annotations

import pytest

from alpha.decision_superiority.gate_isolation_arms import (
    GateIsolationArmBuilder,
    prove_inclusion_minimal,
)
from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualSemanticStatus,
    FrozenCandidateKey,
)


def _candidate() -> FrozenCandidateKey:
    return FrozenCandidateKey(
        price_view="RAW",
        observed_on="2026-01-02",
        symbol="AAA",
        input_fingerprint="fp-a",
    )


def test_builder_creates_deterministic_baseline_and_single_gate_arms() -> None:
    batch = GateIsolationArmBuilder().build(
        candidate=_candidate(),
        observed_failure_codes=("GATE_A", "GATE_B"),
    )

    assert batch.baseline.passed_gate_codes == ()
    assert [arm.passed_gate_codes for arm in batch.single_gate_arms] == [
        ("GATE_A",),
        ("GATE_B",),
    ]
    assert all(
        arm.semantic_status is CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT
        for arm in batch.single_gate_arms
    )
    assert len(batch.minimal_remediation_arms) == 1
    assert batch.combinatorial_limit_reached is False


def test_single_observed_failure_is_effective_single_gate_arm() -> None:
    batch = GateIsolationArmBuilder().build(
        candidate=_candidate(),
        observed_failure_codes=("GATE_A",),
    )

    arm = batch.single_gate_arms[0]
    assert arm.clears_all_observed_failures is True
    assert (
        arm.semantic_status
        is CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION
    )


def test_minimal_remediation_set_clears_all_and_proves_minimality() -> None:
    batch = GateIsolationArmBuilder().build(
        candidate=_candidate(),
        observed_failure_codes=("GATE_A", "GATE_B", "GATE_C"),
    )

    arm = batch.minimal_remediation_arms[0]
    assert arm.clears_all_observed_failures is True
    assert prove_inclusion_minimal(arm) is True


def test_builder_fails_closed_at_combinatorial_limit() -> None:
    batch = GateIsolationArmBuilder(max_remediation_set_size=2).build(
        candidate=_candidate(),
        observed_failure_codes=("GATE_A", "GATE_B", "GATE_C"),
    )

    assert batch.combinatorial_limit_reached is True
    assert batch.minimal_remediation_arms == ()
    assert len(batch.single_gate_arms) == 3


def test_builder_rejects_unsorted_or_duplicate_failures() -> None:
    builder = GateIsolationArmBuilder()

    with pytest.raises(ValueError, match="unique, and sorted"):
        builder.build(
            candidate=_candidate(),
            observed_failure_codes=("GATE_B", "GATE_A"),
        )
    with pytest.raises(ValueError, match="unique, and sorted"):
        builder.build(
            candidate=_candidate(),
            observed_failure_codes=("GATE_A", "GATE_A"),
        )


def test_builder_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        GateIsolationArmBuilder(max_remediation_set_size=0)
