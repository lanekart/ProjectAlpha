from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from alpha.decision_lifecycle import (
    DecisionLifecycleEngine,
    LifecycleConfidence,
    LifecycleEvidence,
    LifecycleState,
    LifecycleTransition,
)
from alpha.decision_science import DecisionStabilityAssessment
from alpha.governance import (
    EvidenceRegistry,
    GovernancePolicy,
    GovernanceVerdict,
)

from .orchestrator import (
    AdvisorAuthority,
    AdvisorSignal,
    DecisionContext,
    DecisionOrchestrator,
    OrchestratedDecision,
)


@dataclass(frozen=True, slots=True)
class GovernedSignalAssessment:
    source: str
    original_authority: AdvisorAuthority
    effective_authority: AdvisorAuthority | None
    evidence_ids: tuple[str, ...]
    allowed_evidence_ids: tuple[str, ...]
    diagnostic_evidence_ids: tuple[str, ...]
    blocked_evidence_ids: tuple[str, ...]
    included: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntegratedDecisionResult:
    decision: OrchestratedDecision
    signal_assessments: tuple[GovernedSignalAssessment, ...]
    transition: LifecycleTransition | None
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError(
                "integrated decision result cannot influence production execution"
            )


class GovernedDecisionFlow:
    """Single governed path from advisor evidence to lifecycle transition."""

    def __init__(
        self,
        *,
        registry: EvidenceRegistry,
        policy: GovernancePolicy,
        orchestrator: DecisionOrchestrator | None = None,
        lifecycle: DecisionLifecycleEngine | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.orchestrator = orchestrator or DecisionOrchestrator()
        self.lifecycle = lifecycle or DecisionLifecycleEngine()

    def evaluate(
        self,
        *,
        recommendation_id: str,
        symbol: str,
        context: DecisionContext,
        signals: tuple[AdvisorSignal, ...],
        stability: DecisionStabilityAssessment | None = None,
        previous_state: LifecycleState | None = None,
        occurred_at: datetime | None = None,
    ) -> IntegratedDecisionResult:
        governed_signals: list[AdvisorSignal] = []
        assessments: list[GovernedSignalAssessment] = []
        for signal in signals:
            governed, assessment = self._govern_signal(signal)
            assessments.append(assessment)
            if governed is not None:
                governed_signals.append(governed)

        if not governed_signals:
            raise ValueError("all advisor signals were blocked by evidence governance")

        decision = self.orchestrator.decide(
            recommendation_id=recommendation_id,
            symbol=symbol,
            context=context,
            signals=tuple(governed_signals),
            stability_score=None if stability is None else stability.score,
        )
        transition = self._record_transition(
            decision=decision,
            signals=tuple(governed_signals),
            previous_state=previous_state,
            occurred_at=occurred_at,
        )
        return IntegratedDecisionResult(
            decision=decision,
            signal_assessments=tuple(assessments),
            transition=transition,
        )

    def _govern_signal(
        self,
        signal: AdvisorSignal,
    ) -> tuple[AdvisorSignal | None, GovernedSignalAssessment]:
        allowed: list[str] = []
        diagnostic: list[str] = []
        blocked: list[str] = []
        reasons: list[str] = []

        for evidence_id in signal.evidence_ids:
            try:
                assessment = self.registry.assess(evidence_id, self.policy)
            except KeyError:
                blocked.append(evidence_id)
                reasons.append(f"{evidence_id}: evidence is not registered")
                continue
            if assessment.verdict is GovernanceVerdict.ALLOWED:
                allowed.append(evidence_id)
            elif assessment.verdict is GovernanceVerdict.DIAGNOSTIC_ONLY:
                diagnostic.append(evidence_id)
                reasons.extend(
                    f"{evidence_id}: {reason}" for reason in assessment.reasons
                )
            else:
                blocked.append(evidence_id)
                reasons.extend(
                    f"{evidence_id}: {reason}" for reason in assessment.reasons
                )

        included = bool(allowed or diagnostic) and not blocked
        effective_authority: AdvisorAuthority | None = signal.authority
        governed: AdvisorSignal | None = None
        if included:
            if diagnostic:
                effective_authority = AdvisorAuthority.CONTEXT
            governed = AdvisorSignal(
                source=signal.source,
                proposed_state=signal.proposed_state,
                authority=effective_authority,
                confidence=signal.confidence,
                reason=signal.reason,
                evidence_ids=tuple(sorted(allowed + diagnostic)),
                veto=signal.veto and not diagnostic,
            )
        else:
            effective_authority = None

        return governed, GovernedSignalAssessment(
            source=signal.source,
            original_authority=signal.authority,
            effective_authority=effective_authority,
            evidence_ids=signal.evidence_ids,
            allowed_evidence_ids=tuple(allowed),
            diagnostic_evidence_ids=tuple(diagnostic),
            blocked_evidence_ids=tuple(blocked),
            included=included,
            reasons=tuple(reasons),
        )

    def _record_transition(
        self,
        *,
        decision: OrchestratedDecision,
        signals: tuple[AdvisorSignal, ...],
        previous_state: LifecycleState | None,
        occurred_at: datetime | None,
    ) -> LifecycleTransition | None:
        if previous_state is None:
            return None
        if occurred_at is None:
            raise ValueError("occurred_at is required when recording a transition")
        if previous_state is decision.final_state:
            return None

        winner = next(
            signal for signal in signals if signal.source == decision.winning_source
        )
        evidence = tuple(
            LifecycleEvidence(evidence_id, winner.reason)
            for evidence_id in decision.evidence_ids
        )
        return self.lifecycle.transition(
            recommendation_id=decision.recommendation_id,
            symbol=decision.symbol,
            occurred_at=occurred_at,
            previous_state=previous_state,
            new_state=decision.final_state,
            reason=winner.reason,
            evidence=evidence,
            confidence=_lifecycle_confidence(decision.confidence_score),
        )


def _lifecycle_confidence(score: int) -> LifecycleConfidence:
    if score >= 75:
        return LifecycleConfidence.HIGH
    if score >= 45:
        return LifecycleConfidence.MEDIUM
    return LifecycleConfidence.LOW
