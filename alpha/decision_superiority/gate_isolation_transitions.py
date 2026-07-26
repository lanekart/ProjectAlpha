"""Deterministic downstream transition replay for DSI-002 arms."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
)
from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    CounterfactualSemanticStatus,
    GateIsolationArm,
)


class DownstreamStage(StrEnum):
    """Ordered frozen downstream stages affected by a shadow intervention."""

    NONE = "NONE"
    APPROVAL = "APPROVAL"
    PORTFOLIO_ELIGIBILITY = "PORTFOLIO_ELIGIBILITY"
    ENTRY_READINESS = "ENTRY_READINESS"
    TRADE_FORMATION = "TRADE_FORMATION"
    OUTCOME = "OUTCOME"


class StageEvaluationStatus(StrEnum):
    """Governed status for one stage-specific counterfactual reevaluation."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_REACHED = "NOT_REACHED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class BaselineDownstreamState:
    """Observed frozen downstream state for one governed candidate."""

    approved: bool
    portfolio_eligible: bool
    entry_ready: bool
    trade_formed: bool
    outcome_available: bool

    def __post_init__(self) -> None:
        if self.trade_formed and not self.entry_ready:
            raise ValueError("trade formation requires entry readiness")
        if self.entry_ready and not self.portfolio_eligible:
            raise ValueError("entry readiness requires portfolio eligibility")
        if self.portfolio_eligible and not self.approved:
            raise ValueError("portfolio eligibility requires approval")


@dataclass(frozen=True, slots=True)
class StageEvaluation:
    """Stage-by-stage counterfactual reevaluation outcome."""

    approval: StageEvaluationStatus
    portfolio_eligibility: StageEvaluationStatus
    entry_readiness: StageEvaluationStatus
    trade_formation: StageEvaluationStatus
    outcome: StageEvaluationStatus

    @classmethod
    def unavailable(cls) -> StageEvaluation:
        """Return an explicit fail-closed evaluation when canonical replay is absent."""

        return cls(
            approval=StageEvaluationStatus.UNAVAILABLE,
            portfolio_eligibility=StageEvaluationStatus.NOT_REACHED,
            entry_readiness=StageEvaluationStatus.NOT_REACHED,
            trade_formation=StageEvaluationStatus.NOT_REACHED,
            outcome=StageEvaluationStatus.NOT_REACHED,
        )

    def to_state(self, baseline: BaselineDownstreamState) -> BaselineDownstreamState:
        """Convert a complete stage evaluation to a downstream state.

        Unavailable or not-reached stages preserve the observed baseline rather than
        fabricating a positive transition.
        """

        if self.approval is not StageEvaluationStatus.PASSED:
            return baseline
        approved = True
        if self.portfolio_eligibility is not StageEvaluationStatus.PASSED:
            return BaselineDownstreamState(approved, False, False, False, False)
        if self.entry_readiness is not StageEvaluationStatus.PASSED:
            return BaselineDownstreamState(approved, True, False, False, False)
        if self.trade_formation is not StageEvaluationStatus.PASSED:
            return BaselineDownstreamState(approved, True, True, False, False)
        return BaselineDownstreamState(
            approved=True,
            portfolio_eligible=True,
            entry_ready=True,
            trade_formed=True,
            outcome_available=self.outcome is StageEvaluationStatus.PASSED,
        )


@dataclass(frozen=True, slots=True)
class GateIsolationTransition:
    """Candidate-level result of one frozen-policy arm replay."""

    arm: GateIsolationArm
    baseline: BaselineDownstreamState
    counterfactual: BaselineDownstreamState
    stage_evaluation: StageEvaluation
    first_changed_stage: DownstreamStage
    newly_approved: bool
    newly_portfolio_eligible: bool
    newly_entry_ready: bool
    newly_trade_formed: bool
    semantic_status: CounterfactualSemanticStatus
    unexplained_divergence: bool = False
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI-002 transitions must remain diagnostic-only")
        if self.unexplained_divergence:
            raise ValueError("unexplained downstream divergence must fail closed")
        expected_stage = _first_changed_stage(self.baseline, self.counterfactual)
        if self.first_changed_stage is not expected_stage:
            raise ValueError("first_changed_stage disagrees with observed states")
        expected_flags = (
            not self.baseline.approved and self.counterfactual.approved,
            not self.baseline.portfolio_eligible
            and self.counterfactual.portfolio_eligible,
            not self.baseline.entry_ready and self.counterfactual.entry_ready,
            not self.baseline.trade_formed and self.counterfactual.trade_formed,
        )
        observed_flags = (
            self.newly_approved,
            self.newly_portfolio_eligible,
            self.newly_entry_ready,
            self.newly_trade_formed,
        )
        if observed_flags != expected_flags:
            raise ValueError("transition flags disagree with downstream states")


class GateIsolationTransitionEngine:
    """Replay transitions without inventing unavailable canonical stage outcomes."""

    def replay(
        self,
        *,
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
        baseline: BaselineDownstreamState,
        stage_evaluation: StageEvaluation | None = None,
    ) -> GateIsolationTransition:
        if arm.candidate != candidate.candidate:
            raise ValueError("arm candidate identity does not match baseline candidate")
        if arm.observed_failure_codes != candidate.observed_failure_codes:
            raise ValueError("arm blocker lineage does not match baseline candidate")

        clears = not arm.remaining_failure_codes
        semantic_status = _semantic_status(arm, clears)
        evaluation = stage_evaluation or StageEvaluation.unavailable()

        if arm.arm_type is CounterfactualArmType.BASELINE or not clears:
            counterfactual = baseline
        else:
            counterfactual = evaluation.to_state(baseline)
            if evaluation.approval is StageEvaluationStatus.UNAVAILABLE:
                semantic_status = CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID

        first_changed = _first_changed_stage(baseline, counterfactual)
        return GateIsolationTransition(
            arm=arm,
            baseline=baseline,
            counterfactual=counterfactual,
            stage_evaluation=evaluation,
            first_changed_stage=first_changed,
            newly_approved=(not baseline.approved and counterfactual.approved),
            newly_portfolio_eligible=(
                not baseline.portfolio_eligible and counterfactual.portfolio_eligible
            ),
            newly_entry_ready=(not baseline.entry_ready and counterfactual.entry_ready),
            newly_trade_formed=(
                not baseline.trade_formed and counterfactual.trade_formed
            ),
            semantic_status=semantic_status,
        )


def _semantic_status(
    arm: GateIsolationArm,
    clears: bool,
) -> CounterfactualSemanticStatus:
    if arm.arm_type is CounterfactualArmType.BASELINE:
        return CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT
    if not clears:
        return CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT
    if arm.arm_type is CounterfactualArmType.SINGLE_GATE_PASS:
        return CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION
    if arm.arm_type is CounterfactualArmType.MINIMAL_REMEDIATION_SET:
        return CounterfactualSemanticStatus.VALID_MINIMAL_REMEDIATION_SET
    return CounterfactualSemanticStatus.NOT_SEMANTICALLY_VALID


def _first_changed_stage(
    baseline: BaselineDownstreamState,
    counterfactual: BaselineDownstreamState,
) -> DownstreamStage:
    checks = (
        (DownstreamStage.APPROVAL, baseline.approved, counterfactual.approved),
        (
            DownstreamStage.PORTFOLIO_ELIGIBILITY,
            baseline.portfolio_eligible,
            counterfactual.portfolio_eligible,
        ),
        (
            DownstreamStage.ENTRY_READINESS,
            baseline.entry_ready,
            counterfactual.entry_ready,
        ),
        (
            DownstreamStage.TRADE_FORMATION,
            baseline.trade_formed,
            counterfactual.trade_formed,
        ),
        (
            DownstreamStage.OUTCOME,
            baseline.outcome_available,
            counterfactual.outcome_available,
        ),
    )
    for stage, observed, shadow in checks:
        if observed != shadow:
            return stage
    return DownstreamStage.NONE


__all__ = [
    "BaselineDownstreamState",
    "DownstreamStage",
    "GateIsolationTransition",
    "GateIsolationTransitionEngine",
    "StageEvaluation",
    "StageEvaluationStatus",
]
