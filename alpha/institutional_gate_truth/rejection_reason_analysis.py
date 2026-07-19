from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from alpha.institutional_gate_truth.expectation_analysis import expectation_summary
from alpha.institutional_gate_truth.models import (
    ReasonStatistic,
    RejectionAssessment,
    RejectionClassification,
)
from alpha.institutional_gate_truth.rejection_statistics import (
    average_return,
    classification_counts,
    rate,
)


def reason_statistics(
    assessments: tuple[RejectionAssessment, ...],
    *,
    initial_capital: Decimal,
) -> tuple[ReasonStatistic, ...]:
    primary: dict[str, list[RejectionAssessment]] = defaultdict(list)
    all_failures: dict[str, list[RejectionAssessment]] = defaultdict(list)
    for item in assessments:
        primary[item.candidate.rejection_reason].append(item)
        for reason in item.candidate.rejection_reasons:
            all_failures[reason].append(item)
    rows = tuple(
        _statistic(
            scope=scope,
            reason=reason,
            values=tuple(values),
            initial_capital=initial_capital,
            population_size=len(assessments),
        )
        for scope, grouped in (
            ("PRIMARY", primary),
            ("ALL_FAILURES", all_failures),
        )
        for reason, values in grouped.items()
    )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                0 if item.reason_scope == "PRIMARY" else 1,
                -item.rejected,
                item.rejection_reason,
            ),
        )
    )


def _statistic(
    *,
    scope: str,
    reason: str,
    values: tuple[RejectionAssessment, ...],
    initial_capital: Decimal,
    population_size: int,
) -> ReasonStatistic:
    counts = classification_counts(values)
    correct = counts[RejectionClassification.CORRECT_REJECTION]
    false = counts[RejectionClassification.FALSE_REJECTION]
    marginal = counts[RejectionClassification.MARGINAL]
    uncertain = counts[RejectionClassification.DATA_UNCERTAIN]
    evaluable = correct + false
    expectation = expectation_summary(
        values,
        initial_capital=initial_capital,
        population_size=population_size,
    )
    return ReasonStatistic(
        reason_scope=scope,
        rejection_reason=reason,
        rejected=len(values),
        correct=correct,
        false=false,
        marginal=marginal,
        data_uncertain=uncertain,
        evaluable=evaluable,
        rejection_accuracy_percent=rate(correct, evaluable),
        false_rejection_rate_percent=rate(false, evaluable),
        average_return_percent=average_return(values),
        average_missed_return_percent=expectation.average_missed_return_percent,
        average_avoided_loss_percent=expectation.average_avoided_loss_percent,
        opportunity_value_lost=expectation.opportunity_value_lost,
        capital_protection_gained=expectation.capital_protection_gained,
    )


__all__ = ["reason_statistics"]
