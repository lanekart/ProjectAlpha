from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
)
from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    CounterfactualSemanticStatus,
    FrozenCandidateKey,
    GateIsolationArm,
)
from alpha.decision_superiority.gate_isolation_transitions import (
    BaselineDownstreamState,
    DownstreamStage,
    GateIsolationTransition,
    GateIsolationTransitionEngine,
    StageEvaluation,
    StageEvaluationStatus,
)


def _candidate(
    failures: tuple[str, ...] = ("GATE_A",),
    *,
    resolved: bool = True,
) -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=FrozenCandidateKey(
            price_view="RAW",
            observed_on="2026-01-02",
            symbol="AAA",
            input_fingerprint="fp-a",
        ),
        observed_failure_codes=failures,
        resolved_outcome=resolved,
        outcome_status="RESOLVED" if resolved else "PENDING",
        realized_return_pct=Decimal("5") if resolved else None,
        realized_r=Decimal("1") if resolved else None,
        b5_present=True,
        b7_present=True,
        b10_present=True,
        dsi001_present=True,
    )


def _arm(
    candidate: FrozenBaselineCandidate,
    *,
    arm_type: CounterfactualArmType,
    passed: tuple[str, ...],
) -> GateIsolationArm:
    return GateIsolationArm(
        arm_id=f"arm-{arm_type.value}-{'-'.join(passed) or 'base'}",
        arm_type=arm_type,
        candidate=candidate.candidate,
        passed_gate_codes=passed,
        observed_failure_codes=candidate.observed_failure_codes,
        semantic_status=CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT,
    )


def _rejected() -> BaselineDownstreamState:
    return BaselineDownstreamState(False, False, False, False, False)


def _all_passed(
    *, outcome: StageEvaluationStatus = StageEvaluationStatus.PASSED
) -> StageEvaluation:
    return StageEvaluation(
        approval=StageEvaluationStatus.PASSED,
        portfolio_eligibility=StageEvaluationStatus.PASSED,
        entry_readiness=StageEvaluationStatus.PASSED,
        trade_formation=StageEvaluationStatus.PASSED,
        outcome=outcome,
    )


def test_clear_arm_without_canonical_reevaluation_fails_closed() -> None:
    candidate = _candidate()
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            passed=("GATE_A",),
        ),
        baseline=_rejected(),
    )

    assert transition.first_changed_stage is DownstreamStage.NONE
    assert transition.counterfactual == transition.baseline
    assert transition.stage_evaluation.approval is StageEvaluationStatus.UNAVAILABLE
    assert transition.newly_approved is False
    assert transition.newly_trade_formed is False
    assert (
        transition.semantic_status
        is CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID
    )


def test_explicit_stage_evaluation_replays_all_downstream_stages() -> None:
    candidate = _candidate()
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            passed=("GATE_A",),
        ),
        baseline=_rejected(),
        stage_evaluation=_all_passed(),
    )

    assert transition.first_changed_stage is DownstreamStage.APPROVAL
    assert transition.newly_approved is True
    assert transition.newly_portfolio_eligible is True
    assert transition.newly_entry_ready is True
    assert transition.newly_trade_formed is True
    assert transition.counterfactual.outcome_available is True
    assert (
        transition.semantic_status
        is CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION
    )


def test_stage_chain_stops_at_first_failed_stage() -> None:
    candidate = _candidate()
    evaluation = StageEvaluation(
        approval=StageEvaluationStatus.PASSED,
        portfolio_eligibility=StageEvaluationStatus.FAILED,
        entry_readiness=StageEvaluationStatus.NOT_REACHED,
        trade_formation=StageEvaluationStatus.NOT_REACHED,
        outcome=StageEvaluationStatus.NOT_REACHED,
    )
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            passed=("GATE_A",),
        ),
        baseline=_rejected(),
        stage_evaluation=evaluation,
    )

    assert transition.newly_approved is True
    assert transition.newly_portfolio_eligible is False
    assert transition.newly_entry_ready is False
    assert transition.newly_trade_formed is False


def test_co_blocked_single_gate_arm_has_no_downstream_effect() -> None:
    candidate = _candidate(("GATE_A", "GATE_B"))
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            passed=("GATE_A",),
        ),
        baseline=_rejected(),
        stage_evaluation=_all_passed(),
    )

    assert transition.first_changed_stage is DownstreamStage.NONE
    assert transition.counterfactual == transition.baseline
    assert (
        transition.semantic_status is CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT
    )


def test_minimal_set_requires_explicit_stage_evaluation() -> None:
    candidate = _candidate(("GATE_A", "GATE_B"))
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.MINIMAL_REMEDIATION_SET,
            passed=("GATE_A", "GATE_B"),
        ),
        baseline=_rejected(),
    )

    assert transition.newly_trade_formed is False
    assert (
        transition.semantic_status
        is CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID
    )


def test_unavailable_outcome_does_not_create_outcome_transition() -> None:
    candidate = _candidate(resolved=False)
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
            passed=("GATE_A",),
        ),
        baseline=_rejected(),
        stage_evaluation=_all_passed(outcome=StageEvaluationStatus.UNAVAILABLE),
    )

    assert transition.newly_trade_formed is True
    assert transition.counterfactual.outcome_available is False


def test_baseline_arm_is_identity_replay() -> None:
    candidate = _candidate()
    baseline = _rejected()
    transition = GateIsolationTransitionEngine().replay(
        candidate=candidate,
        arm=_arm(
            candidate,
            arm_type=CounterfactualArmType.BASELINE,
            passed=(),
        ),
        baseline=baseline,
    )

    assert transition.counterfactual == baseline
    assert transition.first_changed_stage is DownstreamStage.NONE


def test_arm_identity_and_blocker_lineage_must_match() -> None:
    other = _candidate()
    mismatched_arm = GateIsolationArm(
        arm_id="wrong",
        arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
        candidate=FrozenCandidateKey("RAW", "2026-01-03", "AAA", "fp-a"),
        passed_gate_codes=("GATE_A",),
        observed_failure_codes=("GATE_A",),
        semantic_status=CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT,
    )
    with pytest.raises(ValueError, match="identity"):
        GateIsolationTransitionEngine().replay(
            candidate=other,
            arm=mismatched_arm,
            baseline=_rejected(),
        )


def test_invalid_stage_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="entry readiness"):
        BaselineDownstreamState(True, True, False, True, False)


def test_unexplained_divergence_fails_closed() -> None:
    candidate = _candidate()
    arm = _arm(
        candidate,
        arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
        passed=("GATE_A",),
    )
    with pytest.raises(ValueError, match="unexplained"):
        GateIsolationTransition(
            arm=arm,
            baseline=_rejected(),
            counterfactual=BaselineDownstreamState(True, True, True, True, True),
            stage_evaluation=_all_passed(),
            first_changed_stage=DownstreamStage.APPROVAL,
            newly_approved=True,
            newly_portfolio_eligible=True,
            newly_entry_ready=True,
            newly_trade_formed=True,
            semantic_status=(
                CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION
            ),
            unexplained_divergence=True,
        )
