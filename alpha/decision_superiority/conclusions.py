"""Governed economic conclusions for decision-superiority diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from alpha.decision_superiority.confidence import (
    ConfidenceStatus,
    EvidenceAssessment,
)
from alpha.decision_superiority.metrics import GateEconomicValue


class EconomicDirection(StrEnum):
    """Observed direction of a gate's net economic value."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class StatisticalDirection(StrEnum):
    """Direction supported by the mean-return confidence interval."""

    NEGATIVE = "NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"
    POSITIVE = "POSITIVE"
    UNAVAILABLE = "UNAVAILABLE"


class GateRecommendation(StrEnum):
    """Diagnostic-only governed recommendation for one gate."""

    RETAIN = "RETAIN"
    REVIEW = "REVIEW"
    REMOVE = "REMOVE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class GateConclusion:
    """Immutable governed conclusion for one rejection gate."""

    gate_code: str
    economic_direction: EconomicDirection
    statistical_direction: StatisticalDirection
    recommendation: GateRecommendation
    reason_code: str
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not self.gate_code.strip():
            raise ValueError("gate_code cannot be empty")

        if not self.reason_code.strip():
            raise ValueError("reason_code cannot be empty")

        if self.production_influence:
            raise ValueError("DSI conclusions must remain diagnostic-only")


def conclude_gate(
    *,
    gate_code: str,
    economic_value: GateEconomicValue,
    evidence: EvidenceAssessment,
) -> GateConclusion:
    """Translate governed value and confidence outputs into one conclusion."""

    economic_direction = classify_economic_direction(economic_value)
    statistical_direction = classify_statistical_direction(evidence)

    if evidence.status is not ConfidenceStatus.SUFFICIENT:
        return GateConclusion(
            gate_code=gate_code,
            economic_direction=economic_direction,
            statistical_direction=statistical_direction,
            recommendation=GateRecommendation.INSUFFICIENT_EVIDENCE,
            reason_code=evidence.insufficiency_reason,
        )

    if (
        economic_direction is EconomicDirection.POSITIVE
        and statistical_direction is StatisticalDirection.NEGATIVE
    ):
        return GateConclusion(
            gate_code=gate_code,
            economic_direction=economic_direction,
            statistical_direction=statistical_direction,
            recommendation=GateRecommendation.RETAIN,
            reason_code="POSITIVE_NET_VALUE_AND_NEGATIVE_REJECTED_RETURN",
        )

    if (
        economic_direction is EconomicDirection.NEGATIVE
        and statistical_direction is StatisticalDirection.POSITIVE
    ):
        return GateConclusion(
            gate_code=gate_code,
            economic_direction=economic_direction,
            statistical_direction=statistical_direction,
            recommendation=GateRecommendation.REMOVE,
            reason_code="NEGATIVE_NET_VALUE_AND_POSITIVE_REJECTED_RETURN",
        )

    if economic_direction is EconomicDirection.NEUTRAL:
        reason_code = "ZERO_NET_GATE_VALUE"
    elif statistical_direction is StatisticalDirection.INCONCLUSIVE:
        reason_code = "MEAN_RETURN_INTERVAL_CROSSES_ZERO"
    else:
        reason_code = "ECONOMIC_AND_STATISTICAL_SIGNALS_CONFLICT"

    return GateConclusion(
        gate_code=gate_code,
        economic_direction=economic_direction,
        statistical_direction=statistical_direction,
        recommendation=GateRecommendation.REVIEW,
        reason_code=reason_code,
    )


def classify_economic_direction(
    economic_value: GateEconomicValue,
) -> EconomicDirection:
    """Classify the sign of governed net gate value."""

    if economic_value.net_gate_value > 0:
        return EconomicDirection.POSITIVE
    if economic_value.net_gate_value < 0:
        return EconomicDirection.NEGATIVE
    return EconomicDirection.NEUTRAL


def classify_statistical_direction(
    evidence: EvidenceAssessment,
) -> StatisticalDirection:
    """Classify the sign supported by the mean-return interval."""

    interval = evidence.mean_return_interval
    if interval is None:
        return StatisticalDirection.UNAVAILABLE
    if interval.upper < 0:
        return StatisticalDirection.NEGATIVE
    if interval.lower > 0:
        return StatisticalDirection.POSITIVE
    return StatisticalDirection.INCONCLUSIVE


def rank_conclusions(
    conclusions: list[GateConclusion],
) -> tuple[GateConclusion, ...]:
    """Return deterministic recommendation-first conclusion ordering."""

    recommendation_order = {
        GateRecommendation.RETAIN: 0,
        GateRecommendation.REVIEW: 1,
        GateRecommendation.REMOVE: 2,
        GateRecommendation.INSUFFICIENT_EVIDENCE: 3,
    }
    return tuple(
        sorted(
            conclusions,
            key=lambda conclusion: (
                recommendation_order[conclusion.recommendation],
                conclusion.gate_code,
            ),
        )
    )
