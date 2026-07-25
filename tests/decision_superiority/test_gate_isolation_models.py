from __future__ import annotations

import pytest

from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    CounterfactualSemanticStatus,
    DSI002GovernanceBoundary,
    FrozenCandidateKey,
    GateIsolationArm,
    GateIsolationReadiness,
)


def _candidate() -> FrozenCandidateKey:
    return FrozenCandidateKey(
        price_view="RAW",
        observed_on="2026-01-02",
        symbol="AAA",
        input_fingerprint="fp-a",
    )


def test_single_gate_arm_preserves_remaining_failures() -> None:
    arm = GateIsolationArm(
        arm_id="RAW|2026-01-02|AAA|PASS:GATE_A",
        arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
        candidate=_candidate(),
        passed_gate_codes=("GATE_A",),
        observed_failure_codes=("GATE_A", "GATE_B"),
        semantic_status=CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT,
    )

    assert arm.remaining_failure_codes == ("GATE_B",)
    assert arm.clears_all_observed_failures is False
    assert arm.production_influence is False


def test_minimal_remediation_arm_can_clear_all_observed_failures() -> None:
    arm = GateIsolationArm(
        arm_id="RAW|2026-01-02|AAA|PASS:GATE_A+GATE_B",
        arm_type=CounterfactualArmType.MINIMAL_REMEDIATION_SET,
        candidate=_candidate(),
        passed_gate_codes=("GATE_A", "GATE_B"),
        observed_failure_codes=("GATE_A", "GATE_B"),
        semantic_status=CounterfactualSemanticStatus.VALID_MINIMAL_REMEDIATION_SET,
    )

    assert arm.remaining_failure_codes == ()
    assert arm.clears_all_observed_failures is True


def test_baseline_arm_cannot_pass_a_gate() -> None:
    with pytest.raises(ValueError, match="baseline arm cannot pass gates"):
        GateIsolationArm(
            arm_id="baseline",
            arm_type=CounterfactualArmType.BASELINE,
            candidate=_candidate(),
            passed_gate_codes=("GATE_A",),
            observed_failure_codes=("GATE_A",),
            semantic_status=CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID,
        )


def test_single_gate_arm_requires_exactly_one_gate() -> None:
    with pytest.raises(ValueError, match="exactly one gate"):
        GateIsolationArm(
            arm_id="single",
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            candidate=_candidate(),
            passed_gate_codes=("GATE_A", "GATE_B"),
            observed_failure_codes=("GATE_A", "GATE_B"),
            semantic_status=CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID,
        )


def test_arm_rejects_unobserved_passed_gate() -> None:
    with pytest.raises(ValueError, match="observed candidate failures"):
        GateIsolationArm(
            arm_id="invalid",
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            candidate=_candidate(),
            passed_gate_codes=("GATE_B",),
            observed_failure_codes=("GATE_A",),
            semantic_status=CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID,
        )


def test_arm_gate_codes_must_be_unique_and_sorted() -> None:
    with pytest.raises(ValueError, match="unique and sorted"):
        GateIsolationArm(
            arm_id="invalid-order",
            arm_type=CounterfactualArmType.MINIMAL_REMEDIATION_SET,
            candidate=_candidate(),
            passed_gate_codes=("GATE_B", "GATE_A"),
            observed_failure_codes=("GATE_A", "GATE_B"),
            semantic_status=CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID,
        )


def test_governance_boundary_defaults_fail_closed() -> None:
    boundary = DSI002GovernanceBoundary()

    assert boundary.causal_claim_permitted is False
    assert boundary.threshold_change_permitted is False
    assert boundary.approval_policy_change_permitted is False
    assert boundary.portfolio_policy_change_permitted is False
    assert boundary.execution_policy_change_permitted is False
    assert boundary.recommendation_influence is False
    assert boundary.execution_influence is False
    assert boundary.active_replay_integration is False
    assert boundary.production_influence is False


def test_governance_boundary_rejects_any_influence() -> None:
    with pytest.raises(ValueError, match="must remain false"):
        DSI002GovernanceBoundary(production_influence=True)


def test_readiness_states_are_stable() -> None:
    assert (
        GateIsolationReadiness.READY.value
        == "READY_FOR_GOVERNED_GATE_ISOLATION_RESEARCH"
    )
    assert (
        GateIsolationReadiness.COMBINATORIAL_LIMIT.value
        == "BLOCKED_BY_COMBINATORIAL_LIMIT"
    )
