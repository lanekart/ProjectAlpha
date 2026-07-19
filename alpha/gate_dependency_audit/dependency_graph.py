from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.gate_dependency_audit.gate_sequence import CORE_GATE_SEQUENCE
from alpha.gate_dependency_audit.models import CandidateGateLineage, DependencyCell

_TWO = Decimal("0.01")


def dependency_matrix(
    lineages: tuple[CandidateGateLineage, ...],
) -> tuple[DependencyCell, ...]:
    population = len(lineages)
    failed = {
        gate.gate_id: {
            item.candidate_id for item in lineages if gate.gate_id in item.failed_gates
        }
        for gate in CORE_GATE_SEQUENCE
    }
    by_id = {item.candidate_id: item for item in lineages}
    rows: list[DependencyCell] = []
    for prior in CORE_GATE_SEQUENCE:
        prior_failed = failed[prior.gate_id]
        prior_passed_ids = set(by_id).difference(prior_failed)
        for evaluated in CORE_GATE_SEQUENCE:
            if prior.gate_id == evaluated.gate_id:
                continue
            evaluated_failed = failed[evaluated.gate_id]
            incremental = prior_passed_ids.intersection(evaluated_failed)
            rows.append(
                DependencyCell(
                    prior_gate=prior.gate_id,
                    evaluated_gate=evaluated.gate_id,
                    population=population,
                    prior_passed=len(prior_passed_ids),
                    evaluated_gate_failures=len(evaluated_failed),
                    incremental_failures_after_prior_pass=len(incremental),
                    conditional_reject_percent=_rate(
                        len(incremental), len(prior_passed_ids)
                    ),
                    standalone_reject_percent=_rate(len(evaluated_failed), population),
                    retained_information_percent=_rate(
                        len(incremental), len(evaluated_failed)
                    ),
                    correct_incremental_rejections=sum(
                        by_id[item_id].outcome_classification == "CORRECT_REJECTION"
                        for item_id in incremental
                    ),
                    false_incremental_rejections=sum(
                        by_id[item_id].outcome_classification == "FALSE_REJECTION"
                        for item_id in incremental
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


__all__ = ["dependency_matrix"]
