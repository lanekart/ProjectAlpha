from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from alpha.autonomous_loop.models import (
    DNADriftAssessment,
    DriftState,
    HypothesisStage,
    ImprovementHypothesis,
    ValidationEvent,
    ValidationGate,
    ValidationResult,
)
from alpha.autonomous_loop.registry import AutonomousLoopRegistry, canonical_json
from alpha.continuous_learning.models import ResearchRecommendation


class EvidenceLinkedHypothesisGenerator:
    """Convert drift and learning evidence into non-promoting research hypotheses."""

    def generate(
        self,
        *,
        created_at: datetime,
        learning: tuple[ResearchRecommendation, ...],
        dna_drifts: tuple[DNADriftAssessment, ...],
    ) -> tuple[ImprovementHypothesis, ...]:
        rows = [self._learning(created_at, item) for item in learning]
        rows.extend(
            self._dna(created_at, item)
            for item in dna_drifts
            if item.state in {DriftState.EARLY_DRIFT, DriftState.SIGNIFICANT_DRIFT}
        )
        return tuple(sorted(rows, key=lambda item: item.hypothesis_id))

    def _learning(
        self, created_at: datetime, item: ResearchRecommendation
    ) -> ImprovementHypothesis:
        return _hypothesis(
            created_at=created_at,
            title=item.title,
            subsystem=item.subsystem,
            statement=item.recommended_research,
            evidence_ids=item.evidence_ids,
            limitations=(
                "Closed Learning Loop evidence is observational and advisory.",
                "No expected gain is inferred and no production threshold changes.",
            ),
        )

    def _dna(
        self, created_at: datetime, item: DNADriftAssessment
    ) -> ImprovementHypothesis:
        return _hypothesis(
            created_at=created_at,
            title=f"Investigate {item.cohort.value} DNA drift",
            subsystem="FORWARD_DNA",
            statement=(
                "Test whether the observed cohort prevalence shift remains stable "
                "under Strategy Lab, chronological walk-forward, and shadow evidence."
            ),
            evidence_ids=(item.drift_id, *item.evidence_ids),
            limitations=(
                item.explanation,
                "Association is not causation and cannot modify policy directly.",
            ),
        )


class GovernedHypothesisRouter:
    """Enforce Strategy Lab -> walk-forward -> shadow -> human approval order."""

    def __init__(self, registry: AutonomousLoopRegistry) -> None:
        self.registry = registry

    def register_and_route(
        self, hypotheses: tuple[ImprovementHypothesis, ...], *, occurred_at: datetime
    ) -> int:
        existing = {item.hypothesis_id for item in self.registry.hypotheses()}
        new = tuple(item for item in hypotheses if item.hypothesis_id not in existing)
        inserted = self.registry.append_hypotheses(new)
        submissions = tuple(
            _validation(
                hypothesis_id=item.hypothesis_id,
                occurred_at=occurred_at,
                gate=ValidationGate.STRATEGY_LAB,
                result=ValidationResult.SUBMITTED,
                evidence_artifact_id=f"strategy-lab-queue:{item.hypothesis_id}",
                explanation=(
                    "Submitted as an inert research specification; no backtest result "
                    "or policy effect is implied."
                ),
                actor="AUTONOMOUS_DECISION_LOOP",
            )
            for item in new
        )
        self.registry.append_validations(submissions)
        return inserted

    def stage(self, hypothesis_id: str) -> HypothesisStage:
        if hypothesis_id not in {
            item.hypothesis_id for item in self.registry.hypotheses()
        }:
            raise KeyError(f"unknown hypothesis: {hypothesis_id}")
        events = tuple(
            item
            for item in self.registry.validation_events()
            if item.hypothesis_id == hypothesis_id
        )
        return _stage(events)

    def record_result(
        self,
        *,
        hypothesis_id: str,
        gate: ValidationGate,
        passed: bool,
        evidence_artifact_id: str,
        explanation: str,
        actor: str,
        occurred_at: datetime,
    ) -> HypothesisStage:
        expected = {
            HypothesisStage.STRATEGY_LAB_PENDING: ValidationGate.STRATEGY_LAB,
            HypothesisStage.WALK_FORWARD_PENDING: ValidationGate.WALK_FORWARD,
            HypothesisStage.SHADOW_VALIDATION_PENDING: (
                ValidationGate.SHADOW_VALIDATION
            ),
        }.get(self.stage(hypothesis_id))
        if expected is None or gate is not expected:
            raise ValueError("validation gate is out of order or already terminal")
        result = ValidationResult.PASSED if passed else ValidationResult.FAILED
        event = _validation(
            hypothesis_id=hypothesis_id,
            occurred_at=occurred_at,
            gate=gate,
            result=result,
            evidence_artifact_id=evidence_artifact_id,
            explanation=explanation,
            actor=actor,
        )
        self.registry.append_validations((event,))
        if passed and gate is not ValidationGate.SHADOW_VALIDATION:
            next_gate = (
                ValidationGate.WALK_FORWARD
                if gate is ValidationGate.STRATEGY_LAB
                else ValidationGate.SHADOW_VALIDATION
            )
            self.registry.append_validations(
                (
                    _validation(
                        hypothesis_id=hypothesis_id,
                        occurred_at=occurred_at,
                        gate=next_gate,
                        result=ValidationResult.SUBMITTED,
                        evidence_artifact_id=(
                            f"{next_gate.value.lower()}-queue:{hypothesis_id}"
                        ),
                        explanation="Submitted to the next isolated validation gate.",
                        actor="AUTONOMOUS_DECISION_LOOP",
                    ),
                )
            )
        return self.stage(hypothesis_id)

    def human_approve(
        self,
        *,
        hypothesis_id: str,
        evidence_artifact_id: str,
        explanation: str,
        actor: str,
        occurred_at: datetime,
    ) -> HypothesisStage:
        if self.stage(hypothesis_id) is not HypothesisStage.HUMAN_APPROVAL_REQUIRED:
            raise ValueError("human approval is allowed only after shadow validation")
        if actor.strip().upper() == "AUTONOMOUS_DECISION_LOOP":
            raise ValueError("human approval actor cannot be the autonomous loop")
        self.registry.append_validations(
            (
                _validation(
                    hypothesis_id=hypothesis_id,
                    occurred_at=occurred_at,
                    gate=ValidationGate.HUMAN_APPROVAL,
                    result=ValidationResult.APPROVED,
                    evidence_artifact_id=evidence_artifact_id,
                    explanation=explanation,
                    actor=actor,
                ),
            )
        )
        return self.stage(hypothesis_id)


def _hypothesis(
    *,
    created_at: datetime,
    title: str,
    subsystem: str,
    statement: str,
    evidence_ids: tuple[str, ...],
    limitations: tuple[str, ...],
) -> ImprovementHypothesis:
    canonical = {
        "title": title,
        "subsystem": subsystem,
        "statement": statement,
        "evidence_ids": sorted(evidence_ids),
    }
    hypothesis_id = (
        "improvement-" + sha256(canonical_json(canonical).encode()).hexdigest()[:20]
    )
    return ImprovementHypothesis(
        hypothesis_id=hypothesis_id,
        created_at=created_at,
        title=title,
        subsystem=subsystem,
        statement=statement,
        evidence_ids=tuple(sorted(set(evidence_ids))),
        limitations=limitations,
        stage=HypothesisStage.STRATEGY_LAB_PENDING,
    )


def _validation(
    *,
    hypothesis_id: str,
    occurred_at: datetime,
    gate: ValidationGate,
    result: ValidationResult,
    evidence_artifact_id: str,
    explanation: str,
    actor: str,
) -> ValidationEvent:
    identity = sha256(
        canonical_json(
            {
                "hypothesis_id": hypothesis_id,
                "gate": gate.value,
                "result": result.value,
                "evidence": evidence_artifact_id,
            }
        ).encode()
    ).hexdigest()[:24]
    return ValidationEvent(
        validation_id=identity,
        hypothesis_id=hypothesis_id,
        occurred_at=occurred_at,
        gate=gate,
        result=result,
        evidence_artifact_id=evidence_artifact_id,
        explanation=explanation,
        actor=actor,
    )


def _stage(events: tuple[ValidationEvent, ...]) -> HypothesisStage:
    by_gate: dict[ValidationGate, ValidationResult] = {}
    for event in events:
        if event.result is not ValidationResult.SUBMITTED:
            by_gate[event.gate] = event.result
    if by_gate.get(ValidationGate.STRATEGY_LAB) is ValidationResult.FAILED:
        return HypothesisStage.REJECTED
    if by_gate.get(ValidationGate.STRATEGY_LAB) is not ValidationResult.PASSED:
        return HypothesisStage.STRATEGY_LAB_PENDING
    if by_gate.get(ValidationGate.WALK_FORWARD) is ValidationResult.FAILED:
        return HypothesisStage.REJECTED
    if by_gate.get(ValidationGate.WALK_FORWARD) is not ValidationResult.PASSED:
        return HypothesisStage.WALK_FORWARD_PENDING
    if by_gate.get(ValidationGate.SHADOW_VALIDATION) is ValidationResult.FAILED:
        return HypothesisStage.REJECTED
    if by_gate.get(ValidationGate.SHADOW_VALIDATION) is not ValidationResult.PASSED:
        return HypothesisStage.SHADOW_VALIDATION_PENDING
    if by_gate.get(ValidationGate.HUMAN_APPROVAL) is ValidationResult.APPROVED:
        return HypothesisStage.HUMAN_APPROVED
    return HypothesisStage.HUMAN_APPROVAL_REQUIRED


__all__ = [
    "EvidenceLinkedHypothesisGenerator",
    "GovernedHypothesisRouter",
]
