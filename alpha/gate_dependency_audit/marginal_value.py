from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.gate_dependency_audit.gate_sequence import CORE_GATE_SEQUENCE
from alpha.gate_dependency_audit.models import (
    CandidateGateLineage,
    MarginalGateValue,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def marginal_gate_values(
    lineages: tuple[CandidateGateLineage, ...],
    *,
    initial_capital: Decimal,
) -> tuple[MarginalGateValue, ...]:
    notional = _ZERO if not lineages else initial_capital / Decimal(len(lineages))
    rows: list[MarginalGateValue] = []
    for gate in CORE_GATE_SEQUENCE:
        failed = tuple(item for item in lineages if gate.gate_id in item.failed_gates)
        released = tuple(
            item for item in failed if item.failed_gates == (gate.gate_id,)
        )
        false = tuple(
            item
            for item in released
            if item.outcome_classification == "FALSE_REJECTION"
        )
        correct = tuple(
            item
            for item in released
            if item.outcome_classification == "CORRECT_REJECTION"
        )
        lost = _economic_value(false, notional, positive=True)
        protected = _economic_value(correct, notional, positive=False)
        net = protected - lost
        rows.append(
            MarginalGateValue(
                gate_id=gate.gate_id,
                display_name=gate.display_name,
                gate_group=gate.group,
                candidates_failed_gate=len(failed),
                additional_survivors_if_removed=len(released),
                correct_rejections_released=len(correct),
                false_rejections_released=len(false),
                marginal_released=sum(
                    item.outcome_classification == "MARGINAL" for item in released
                ),
                data_uncertain_released=sum(
                    item.outcome_classification == "DATA_UNCERTAIN" for item in released
                ),
                average_return_percent=_mean_return(released),
                opportunity_value_lost=lost,
                capital_protection_gained=protected,
                net_capital_protection=_q(net),
                diagnostic_conclusion=_conclusion(
                    released=len(released),
                    net=net,
                    false=len(false),
                    correct=len(correct),
                ),
            )
        )
    return tuple(rows)


def _economic_value(
    rows: tuple[CandidateGateLineage, ...],
    notional: Decimal,
    *,
    positive: bool,
) -> Decimal:
    values = tuple(
        item.planned_net_return_percent
        for item in rows
        if item.planned_net_return_percent is not None
        and (
            item.planned_net_return_percent > 0
            if positive
            else item.planned_net_return_percent < 0
        )
    )
    return _q(
        sum(
            (notional * abs(value) / Decimal("100") for value in values),
            start=_ZERO,
        )
    )


def _mean_return(
    rows: tuple[CandidateGateLineage, ...],
) -> Decimal | None:
    values = tuple(
        item.planned_net_return_percent
        for item in rows
        if item.planned_net_return_percent is not None
    )
    if not values:
        return None
    return _q(sum(values, _ZERO) / Decimal(len(values)))


def _conclusion(*, released: int, net: Decimal, false: int, correct: int) -> str:
    if released == 0:
        return "REDUNDANT_AFTER_OTHER_GATES"
    if net > 0:
        return "MARGINAL_CAPITAL_PROTECTION_POSITIVE"
    if net < 0:
        return "MARGINAL_OPPORTUNITY_COST_EXCEEDS_PROTECTION"
    if false == correct:
        return "MARGINAL_VALUE_BALANCED"
    return "MARGINAL_VALUE_UNRESOLVED"


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["marginal_gate_values"]
