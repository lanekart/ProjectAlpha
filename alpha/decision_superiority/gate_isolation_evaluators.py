"""Governed stage evaluator contracts for DSI-002 counterfactual replay."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
)
from alpha.decision_superiority.gate_isolation_models import GateIsolationArm
from alpha.decision_superiority.gate_isolation_transitions import (
    StageEvaluation,
    StageEvaluationStatus,
)


class GateIsolationStageEvaluator(Protocol):
    """Evaluate one cleared arm through frozen downstream stages."""

    def evaluate(
        self,
        *,
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluation:
        """Return deterministic stage outcomes for a cleared counterfactual arm."""


StageCallable = Callable[[FrozenBaselineCandidate, GateIsolationArm], StageEvaluationStatus]


@dataclass(frozen=True, slots=True)
class FrozenPolicyStageEvaluator:
    """Compose explicit frozen-policy stage functions with fail-closed chaining."""

    approval: StageCallable
    portfolio_eligibility: StageCallable
    entry_readiness: StageCallable
    trade_formation: StageCallable
    outcome: StageCallable

    def evaluate(
        self,
        *,
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluation:
        """Run stages in order and stop immediately after failure or unavailability."""

        if arm.candidate != candidate.candidate:
            raise ValueError("evaluator arm identity does not match candidate")
        if arm.remaining_failure_codes:
            raise ValueError("stage evaluator requires a fully cleared arm")

        approval = self.approval(candidate, arm)
        if approval is not StageEvaluationStatus.PASSED:
            return StageEvaluation(
                approval=approval,
                portfolio_eligibility=StageEvaluationStatus.NOT_REACHED,
                entry_readiness=StageEvaluationStatus.NOT_REACHED,
                trade_formation=StageEvaluationStatus.NOT_REACHED,
                outcome=StageEvaluationStatus.NOT_REACHED,
            )

        portfolio = self.portfolio_eligibility(candidate, arm)
        if portfolio is not StageEvaluationStatus.PASSED:
            return StageEvaluation(
                approval=approval,
                portfolio_eligibility=portfolio,
                entry_readiness=StageEvaluationStatus.NOT_REACHED,
                trade_formation=StageEvaluationStatus.NOT_REACHED,
                outcome=StageEvaluationStatus.NOT_REACHED,
            )

        entry = self.entry_readiness(candidate, arm)
        if entry is not StageEvaluationStatus.PASSED:
            return StageEvaluation(
                approval=approval,
                portfolio_eligibility=portfolio,
                entry_readiness=entry,
                trade_formation=StageEvaluationStatus.NOT_REACHED,
                outcome=StageEvaluationStatus.NOT_REACHED,
            )

        trade = self.trade_formation(candidate, arm)
        if trade is not StageEvaluationStatus.PASSED:
            return StageEvaluation(
                approval=approval,
                portfolio_eligibility=portfolio,
                entry_readiness=entry,
                trade_formation=trade,
                outcome=StageEvaluationStatus.NOT_REACHED,
            )

        outcome = self.outcome(candidate, arm)
        return StageEvaluation(
            approval=approval,
            portfolio_eligibility=portfolio,
            entry_readiness=entry,
            trade_formation=trade,
            outcome=outcome,
        )


@dataclass(frozen=True, slots=True)
class UnavailableStageEvaluator:
    """Explicit default until canonical frozen-policy evaluators are supplied."""

    def evaluate(
        self,
        *,
        candidate: FrozenBaselineCandidate,
        arm: GateIsolationArm,
    ) -> StageEvaluation:
        """Fail closed without manufacturing any downstream decision."""

        if arm.candidate != candidate.candidate:
            raise ValueError("evaluator arm identity does not match candidate")
        if arm.remaining_failure_codes:
            raise ValueError("stage evaluator requires a fully cleared arm")
        return StageEvaluation.unavailable()


__all__ = [
    "FrozenPolicyStageEvaluator",
    "GateIsolationStageEvaluator",
    "StageCallable",
    "UnavailableStageEvaluator",
]
