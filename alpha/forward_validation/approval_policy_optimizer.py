from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
)
from alpha.forward_validation.approval_gate_optimizer import (
    ApprovalGateOptimizer,
    primary_window,
    record_stop_distance,
)
from alpha.forward_validation.counterfactual_engine import (
    CounterfactualPolicyEngine,
    shortlist_validated,
)
from alpha.forward_validation.models import (
    ApprovalOptimizationReport,
    CounterfactualPolicy,
    OptimizationRecommendation,
    PolicyVersion,
    StopAuditClassification,
    StopDistanceAudit,
)


class ApprovalPolicyOptimizer:
    """Optimize policy candidates offline while preserving V1 production policy."""

    def __init__(
        self,
        *,
        gate_optimizer: ApprovalGateOptimizer | None = None,
        counterfactual_engine: CounterfactualPolicyEngine | None = None,
    ) -> None:
        self.gate_optimizer = gate_optimizer or ApprovalGateOptimizer()
        self.counterfactual_engine = (
            counterfactual_engine or CounterfactualPolicyEngine(self.gate_optimizer)
        )

    def optimize(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> ApprovalOptimizationReport:
        gate_metrics = self.gate_optimizer.analyze(
            records=records,
            outcomes=outcomes,
        )
        generated = self.counterfactual_engine.generate(records)
        validated = self.counterfactual_engine.validate(
            candidates=generated,
            records=records,
            outcomes=outcomes,
        )
        shortlisted = shortlist_validated(validated)
        presented = _presented_candidates(shortlisted, validated)
        recommendation, reason = _recommendation(shortlisted)
        stop_audit = self.stop_distance_audit(records=records, outcomes=outcomes)
        if shortlisted:
            stop_candidate = next(
                (
                    candidate
                    for candidate in shortlisted
                    if candidate.parameters.get("gate_id") == "stop_distance"
                    and candidate.operation.value == "RELAX"
                ),
                None,
            )
            if stop_candidate is not None:
                stop_audit = replace(
                    stop_audit,
                    recommended_threshold_pct=Decimal(
                        stop_candidate.parameters["threshold"]
                    ),
                    findings=stop_audit.findings
                    + (
                        "The threshold survived training, validation, and hold-out "
                        "replay; deploy only to frozen forward validation.",
                    ),
                )
        outcome_population = sum(
            1
            for record in records
            if primary_window(
                next(
                    (
                        outcome
                        for outcome in outcomes
                        if outcome.candidate_id == record.candidate_id
                    ),
                    None,
                )
            )
            is not None
        )
        return ApprovalOptimizationReport(
            generated_at=datetime.now(tz=UTC),
            policy_version=PolicyVersion("APPROVAL_POLICY_V1"),
            source_population=len(records),
            outcome_population=outcome_population,
            gates=gate_metrics,
            stop_distance_audit=stop_audit,
            candidates=presented,
            recommendation=recommendation,
            recommendation_reason=reason,
        )

    def stop_distance_audit(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> StopDistanceAudit:
        gates_before = self.gate_optimizer.gates[:7]
        at_gate = tuple(
            record
            for record in records
            if all(gate.predicate(record) for gate in gates_before)
        )
        distances = tuple(
            distance
            for record in at_gate
            if (distance := record_stop_distance(record)) is not None
        )
        passing = tuple(distance for distance in distances if distance <= Decimal("10"))
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        rejected = tuple(
            record
            for record in at_gate
            if (distance := record_stop_distance(record)) is None
            or distance > Decimal("10")
        )
        profitable_rejections = sum(
            1
            for record in rejected
            if (window := primary_window(outcome_by_id.get(record.candidate_id)))
            is not None
            and window.forward_return_pct_from_entry is not None
            and window.forward_return_pct_from_entry > Decimal("0")
        )
        classification, findings, correction = _classify_stop_audit(
            at_gate=at_gate,
            distances=distances,
            passing=passing,
            profitable_rejections=profitable_rejections,
        )
        return StopDistanceAudit(
            classification=classification,
            evaluated_candidates=len(records),
            distance_available=len(distances),
            candidates_at_gate=len(at_gate),
            candidates_passing=len(passing),
            profitable_rejections=profitable_rejections,
            minimum_distance_pct=min(distances, default=None),
            median_distance_pct=_median(distances),
            maximum_distance_pct=max(distances, default=None),
            current_threshold_pct=Decimal("10"),
            recommended_threshold_pct=None,
            implementation_correction=correction,
            findings=findings,
        )


def _classify_stop_audit(
    *,
    at_gate: tuple[CandidateDecisionRecord, ...],
    distances: tuple[Decimal, ...],
    passing: tuple[Decimal, ...],
    profitable_rejections: int,
) -> tuple[StopAuditClassification, tuple[str, ...], str | None]:
    if not at_gate:
        return (
            StopAuditClassification.UNKNOWN,
            ("No candidate reached the stop-distance gate.",),
            None,
        )
    if not distances:
        return (
            StopAuditClassification.DATA_DEFECT,
            ("No candidate reaching the gate had both entry and stop data.",),
            "Freeze entry and stop levels before approval evaluation.",
        )
    if any(distance < Decimal("0") for distance in distances):
        return (
            StopAuditClassification.SCALE_DEFECT,
            (
                "At least one long stop is above its entry, producing negative "
                "distance.",
            ),
            "Reject structurally invalid long stops before percentage normalization.",
        )
    if any(distance > Decimal("100") for distance in distances):
        return (
            StopAuditClassification.UNIT_DEFECT,
            ("At least one normalized stop distance exceeds 100 percent.",),
            "Audit entry/stop currency units before policy evaluation.",
        )
    findings: tuple[str, ...] = (
        "Distance uses (entry - stop) / entry x 100 and is rounded half-up to "
        "two decimals.",
        "ATR is not used by V1's stop-distance gate; no hidden ATR "
        "normalization occurs.",
        "V1 applies no volatility normalization after calculating the percent "
        "distance.",
        f"Entry-and-stop data was available for {len(distances)} of "
        f"{len(at_gate)} candidates reaching the gate.",
    )
    if not passing:
        findings += (
            "The current threshold passed none of the candidates that reached "
            "this gate.",
        )
    if not passing and profitable_rejections > 0:
        return (
            StopAuditClassification.OVER_RESTRICTIVE,
            findings
            + ("The observed gate rejected profitable candidates and passed none.",),
            None,
        )
    return (
        StopAuditClassification.VALID_POLICY,
        findings + ("Observed distances are internally coherent under V1 units.",),
        None,
    )


def _presented_candidates(
    shortlisted: tuple[CounterfactualPolicy, ...],
    validated: tuple[CounterfactualPolicy, ...],
) -> tuple[CounterfactualPolicy, ...]:
    selected_descriptions = {candidate.description for candidate in shortlisted}
    remainder = tuple(
        candidate
        for candidate in validated
        if candidate.description not in selected_descriptions
    )
    starting_version = 4 if shortlisted else 2
    reversioned = tuple(
        replace(
            candidate,
            policy_version=PolicyVersion(f"APPROVAL_POLICY_V{index}"),
        )
        for index, candidate in enumerate(remainder, start=starting_version)
    )
    return shortlisted + reversioned


def _recommendation(
    shortlisted: tuple[CounterfactualPolicy, ...],
) -> tuple[OptimizationRecommendation, str]:
    if not shortlisted:
        return (
            OptimizationRecommendation.NO_VALID_POLICY_FOUND,
            "No candidate survived training, validation, and hold-out replay "
            "without degradation.",
        )
    best = shortlisted[0]
    if best.policy_version.number == 2:
        return (
            OptimizationRecommendation.DEPLOY_POLICY_V2_TO_FORWARD_VALIDATION,
            "Policy V2 survived all offline splits; it remains diagnostic until "
            "frozen forward evidence matures.",
        )
    if best.policy_version.number == 3:
        return (
            OptimizationRecommendation.DEPLOY_POLICY_V3_TO_FORWARD_VALIDATION,
            "Policy V3 survived all offline splits; it remains diagnostic until "
            "frozen forward evidence matures.",
        )
    return (
        OptimizationRecommendation.KEEP_POLICY_V1,
        "No permitted candidate policy version is ready for forward validation.",
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


__all__ = ["ApprovalPolicyOptimizer"]
