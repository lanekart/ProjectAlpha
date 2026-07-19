from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from itertools import permutations

from alpha.gate_dependency_audit.gate_sequence import CORE_GATE_SEQUENCE
from alpha.gate_dependency_audit.models import (
    CandidateGateLineage,
    GateOrderAssessment,
)

_FOUR = Decimal("0.0001")


def evaluate_gate_order(
    lineages: tuple[CandidateGateLineage, ...],
) -> GateOrderAssessment:
    active = tuple(
        gate.gate_id
        for gate in CORE_GATE_SEQUENCE
        if any(gate.gate_id in item.failed_gates for item in lineages)
    )
    failed_sets = tuple(frozenset(item.failed_gates) for item in lineages)
    current_average = _average_evaluations(active, failed_sets)
    best_order = active
    best_average = current_average
    equally_efficient = 0
    tested = 0
    for order in permutations(active):
        tested += 1
        average = _average_evaluations(order, failed_sets)
        if average < best_average:
            best_order = order
            best_average = average
            equally_efficient = 1
        elif average == best_average:
            equally_efficient += 1
            if order < best_order:
                best_order = order
    accepted = sum(not item.failed_gates for item in lineages)
    false_rejections = sum(
        item.outcome_classification == "FALSE_REJECTION" and bool(item.failed_gates)
        for item in lineages
    )
    improvement = (
        Decimal("0")
        if current_average <= 0
        else (current_average - best_average) / current_average * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return GateOrderAssessment(
        current_order=active,
        most_efficient_order=best_order,
        active_gate_count=len(active),
        permutations_tested=tested,
        equally_efficient_orders=equally_efficient,
        current_average_gates_evaluated=current_average,
        minimum_average_gates_evaluated=best_average,
        efficiency_improvement_percent=improvement,
        accepted_current_order=accepted,
        accepted_best_order=accepted,
        false_rejections_current_order=false_rejections,
        false_rejections_best_order=false_rejections,
        decision_outcomes_changed=False,
        conclusion=(
            "Gate order cannot change decisions because all frozen criteria are "
            "combined with logical AND. Reordering only changes first-failure "
            "attribution and potential short-circuit evaluation cost."
        ),
    )


def _average_evaluations(
    order: tuple[str, ...],
    failed_sets: tuple[frozenset[str], ...],
) -> Decimal:
    if not failed_sets or not order:
        return Decimal("0")
    total = 0
    for failures in failed_sets:
        total += next(
            (
                index
                for index, gate_id in enumerate(order, start=1)
                if gate_id in failures
            ),
            len(order),
        )
    return (Decimal(total) / Decimal(len(failed_sets))).quantize(_FOUR)


__all__ = ["evaluate_gate_order"]
