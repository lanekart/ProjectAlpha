from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
)
from alpha.decision_superiority.gate_isolation_evaluators import (
    FrozenPolicyStageEvaluator,
    UnavailableStageEvaluator,
)
from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    CounterfactualSemanticStatus,
    FrozenCandidateKey,
    GateIsolationArm,
)
from alpha.decision_superiority.gate_isolation_transitions import (
    StageEvaluationStatus,
)


def _candidate() -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=FrozenCandidateKey("RAW", "2026-01-02", "AAA", "fp-a"),
        observed_failure_codes=("GATE_A",),
        resolved_outcome=True,
        outcome_status="RESOLVED",
        realized_return_pct=Decimal("5"),
        realized_r=Decimal("1"),
        b5_present=True,
        b7_present=True,
        b10_present=True,
        dsi001_present=True,
    )


def _cleared_arm(candidate: FrozenBaselineCandidate) -> GateIsolationArm:
    return GateIsolationArm(
        arm_id="arm-a",
        arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
        candidate=candidate.candidate,
        passed_gate_codes=("GATE_A",),
        observed_failure_codes=("GATE_A",),
        semantic_status=CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION,
    )


def _status(value: StageEvaluationStatus):
    def evaluate(
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluationStatus:
        del candidate, arm
        return value

    return evaluate


def test_frozen_evaluator_passes_all_stages_in_order() -> None:
    candidate = _candidate()
    evaluation = FrozenPolicyStageEvaluator(
        approval=_status(StageEvaluationStatus.PASSED),
        portfolio_eligibility=_status(StageEvaluationStatus.PASSED),
        entry_readiness=_status(StageEvaluationStatus.PASSED),
        trade_formation=_status(StageEvaluationStatus.PASSED),
        outcome=_status(StageEvaluationStatus.PASSED),
    ).evaluate(candidate=candidate, arm=_cleared_arm(candidate))

    assert evaluation.approval is StageEvaluationStatus.PASSED
    assert evaluation.portfolio_eligibility is StageEvaluationStatus.PASSED
    assert evaluation.entry_readiness is StageEvaluationStatus.PASSED
    assert evaluation.trade_formation is StageEvaluationStatus.PASSED
    assert evaluation.outcome is StageEvaluationStatus.PASSED


def test_frozen_evaluator_stops_after_failed_approval() -> None:
    candidate = _candidate()
    calls: list[str] = []

    def approval(
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluationStatus:
        del candidate, arm
        calls.append("approval")
        return StageEvaluationStatus.FAILED

    def must_not_run(
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluationStatus:
        del candidate, arm
        raise AssertionError("downstream stage must not run")

    evaluation = FrozenPolicyStageEvaluator(
        approval=approval,
        portfolio_eligibility=must_not_run,
        entry_readiness=must_not_run,
        trade_formation=must_not_run,
        outcome=must_not_run,
    ).evaluate(candidate=candidate, arm=_cleared_arm(candidate))

    assert calls == ["approval"]
    assert evaluation.approval is StageEvaluationStatus.FAILED
    assert evaluation.portfolio_eligibility is StageEvaluationStatus.NOT_REACHED
    assert evaluation.entry_readiness is StageEvaluationStatus.NOT_REACHED
    assert evaluation.trade_formation is StageEvaluationStatus.NOT_REACHED
    assert evaluation.outcome is StageEvaluationStatus.NOT_REACHED


def test_unavailable_evaluator_is_explicitly_fail_closed() -> None:
    candidate = _candidate()
    evaluation = UnavailableStageEvaluator().evaluate(
        candidate=candidate,
        arm=_cleared_arm(candidate),
    )

    assert evaluation.approval is StageEvaluationStatus.UNAVAILABLE
    assert evaluation.portfolio_eligibility is StageEvaluationStatus.NOT_REACHED


def test_evaluator_rejects_uncleared_arm() -> None:
    candidate = _candidate()
    arm = GateIsolationArm(
        arm_id="baseline",
        arm_type=CounterfactualArmType.BASELINE,
        candidate=candidate.candidate,
        passed_gate_codes=(),
        observed_failure_codes=("GATE_A",),
        semantic_status=CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT,
    )

    with pytest.raises(ValueError, match="fully cleared"):
        UnavailableStageEvaluator().evaluate(candidate=candidate, arm=arm)
