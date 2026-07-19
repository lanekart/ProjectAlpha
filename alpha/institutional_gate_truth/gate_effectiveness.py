from __future__ import annotations

from decimal import Decimal

from alpha.institutional_gate_truth.expectation_analysis import expectation_summary
from alpha.institutional_gate_truth.models import (
    ConclusionConfidence,
    CounterfactualStatistics,
    GateEffectiveness,
    GateTruthConclusion,
    RejectionAssessment,
    RejectionClassification,
)
from alpha.institutional_gate_truth.rejection_statistics import (
    classification_counts,
    rate,
)


def gate_effectiveness(
    assessments: tuple[RejectionAssessment, ...],
    *,
    initial_capital: Decimal,
    counterfactual: CounterfactualStatistics,
) -> GateEffectiveness:
    counts = classification_counts(assessments)
    correct = counts[RejectionClassification.CORRECT_REJECTION]
    false = counts[RejectionClassification.FALSE_REJECTION]
    marginal = counts[RejectionClassification.MARGINAL]
    uncertain = counts[RejectionClassification.DATA_UNCERTAIN]
    evaluable = correct + false
    expectation = expectation_summary(
        assessments,
        initial_capital=initial_capital,
        population_size=len(assessments),
    )
    confidence, confidence_reason = _confidence(
        population=len(assessments),
        evaluable=evaluable,
        uncertain=uncertain,
    )
    conclusion, recommendation = _conclusion(
        evaluable=evaluable,
        value_lost=expectation.opportunity_value_lost,
        value_preserved=expectation.capital_protection_gained,
        counterfactual=counterfactual,
    )
    return GateEffectiveness(
        rejected_population=len(assessments),
        correct_rejections=correct,
        false_rejections=false,
        marginal_rejections=marginal,
        data_uncertain_rejections=uncertain,
        evaluable_rejections=evaluable,
        overall_rejection_accuracy_percent=rate(correct, evaluable),
        overall_false_rejection_rate_percent=rate(false, evaluable),
        expected_value_preserved=expectation.expected_value_preserved,
        expected_value_lost=expectation.expected_value_lost,
        average_missed_return_percent=expectation.average_missed_return_percent,
        average_avoided_loss_percent=expectation.average_avoided_loss_percent,
        opportunity_value_lost=expectation.opportunity_value_lost,
        capital_protection_gained=expectation.capital_protection_gained,
        opportunity_capture_lost_percent=rate(false, len(assessments)),
        confidence=confidence,
        confidence_reason=confidence_reason,
        conclusion=conclusion,
        primary_recommendation=recommendation,
    )


def _confidence(
    *,
    population: int,
    evaluable: int,
    uncertain: int,
) -> tuple[ConclusionConfidence, str]:
    uncertain_rate = (
        Decimal(uncertain) / Decimal(population) if population else Decimal("1")
    )
    if evaluable >= 100 and uncertain_rate <= Decimal("0.25"):
        return (
            ConclusionConfidence.MEDIUM,
            "Large frozen support, but the provisional legacy warehouse and "
            "lack of an independent holdout cap confidence at MEDIUM.",
        )
    return (
        ConclusionConfidence.LOW,
        "Support, outcome maturity, or warehouse certainty is insufficient "
        "for a stronger conclusion.",
    )


def _conclusion(
    *,
    evaluable: int,
    value_lost: Decimal,
    value_preserved: Decimal,
    counterfactual: CounterfactualStatistics,
) -> tuple[GateTruthConclusion, str]:
    if evaluable < 30 or counterfactual.cagr_percent is None:
        return (
            GateTruthConclusion.INSUFFICIENT_EVIDENCE,
            "Keep the frozen gate unchanged and mature more outcome evidence.",
        )
    if value_lost > value_preserved and counterfactual.cagr_percent > 0:
        return (
            GateTruthConclusion.GATE_SUPPRESSES_EDGE,
            "Investigate the institutional gate as the dominant bottleneck in "
            "a separate offline experiment; do not change production.",
        )
    if value_preserved > value_lost and counterfactual.cagr_percent <= 0:
        return (
            GateTruthConclusion.GATE_PROTECTS_CAPITAL,
            "Retain the frozen gate and focus the next research sprint on "
            "upstream candidate quality.",
        )
    return (
        GateTruthConclusion.MIXED_EVIDENCE,
        "Retain the frozen gate and run reason-specific chronological "
        "validation before proposing any policy change.",
    )


__all__ = ["gate_effectiveness"]
