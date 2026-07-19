from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

from alpha.gate_dependency_audit.gate_sequence import CORE_GATE_SEQUENCE
from alpha.gate_dependency_audit.models import CandidateGateLineage, InteractionCell

_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")


def interaction_matrix(
    lineages: tuple[CandidateGateLineage, ...],
) -> tuple[InteractionCell, ...]:
    population = len(lineages)
    by_id = {item.candidate_id: item for item in lineages}
    failed = {
        gate.gate_id: {
            item.candidate_id for item in lineages if gate.gate_id in item.failed_gates
        }
        for gate in CORE_GATE_SEQUENCE
    }
    rows: list[InteractionCell] = []
    for gate_a, gate_b in combinations(CORE_GATE_SEQUENCE, 2):
        failures_a = failed[gate_a.gate_id]
        failures_b = failed[gate_b.gate_id]
        joint = failures_a.intersection(failures_b)
        union = failures_a.union(failures_b)
        neither = set(by_id).difference(union)
        base_b = (
            None if population == 0 else Decimal(len(failures_b)) / Decimal(population)
        )
        conditional_b = (
            None if not failures_a else Decimal(len(joint)) / Decimal(len(failures_a))
        )
        lift = (
            None
            if base_b is None or base_b == 0 or conditional_b is None
            else (conditional_b / base_b).quantize(_FOUR)
        )
        rows.append(
            InteractionCell(
                gate_a=gate_a.gate_id,
                gate_b=gate_b.gate_id,
                population=population,
                gate_a_failures=len(failures_a),
                gate_b_failures=len(failures_b),
                joint_failures=len(joint),
                only_a_failures=len(failures_a.difference(failures_b)),
                only_b_failures=len(failures_b.difference(failures_a)),
                neither_failures=len(neither),
                jaccard_percent=_rate(len(joint), len(union)),
                interaction_lift=lift,
                joint_correct_rejections=sum(
                    by_id[item_id].outcome_classification == "CORRECT_REJECTION"
                    for item_id in joint
                ),
                joint_false_rejections=sum(
                    by_id[item_id].outcome_classification == "FALSE_REJECTION"
                    for item_id in joint
                ),
            )
        )
    return tuple(rows)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["interaction_matrix"]
