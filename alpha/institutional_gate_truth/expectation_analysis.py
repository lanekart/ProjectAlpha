from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from alpha.institutional_gate_truth.models import (
    RejectionAssessment,
    RejectionClassification,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ExpectationSummary:
    expected_value_lost: Decimal
    expected_value_preserved: Decimal
    average_missed_return_percent: Decimal | None
    average_avoided_loss_percent: Decimal | None
    opportunity_value_lost: Decimal
    capital_protection_gained: Decimal


def expectation_summary(
    assessments: tuple[RejectionAssessment, ...],
    *,
    initial_capital: Decimal,
    population_size: int,
) -> ExpectationSummary:
    false_returns = _returns(assessments, RejectionClassification.FALSE_REJECTION)
    correct_returns = _returns(assessments, RejectionClassification.CORRECT_REJECTION)
    positive = tuple(value for value in false_returns if value > 0)
    negative = tuple(abs(value) for value in correct_returns if value < 0)
    notional = (
        _ZERO if population_size <= 0 else initial_capital / Decimal(population_size)
    )
    lost = sum((notional * value / Decimal("100") for value in positive), _ZERO)
    protected = sum((notional * value / Decimal("100") for value in negative), _ZERO)
    return ExpectationSummary(
        expected_value_lost=_mean(positive) or _ZERO,
        expected_value_preserved=_mean(negative) or _ZERO,
        average_missed_return_percent=_mean(positive),
        average_avoided_loss_percent=_mean(negative),
        opportunity_value_lost=_q(lost),
        capital_protection_gained=_q(protected),
    )


def _returns(
    assessments: tuple[RejectionAssessment, ...],
    classification: RejectionClassification,
) -> tuple[Decimal, ...]:
    return tuple(
        value
        for item in assessments
        if item.classification is classification
        and (value := item.planned_outcome.net_return_percent) is not None
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(sum(values, _ZERO) / Decimal(len(values)))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["ExpectationSummary", "expectation_summary"]
