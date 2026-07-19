"""Data decision-value and cost-adjusted prioritization engine."""

from __future__ import annotations

from alpha.data_value_audit.cost_model import CostModel
from alpha.data_value_audit.decision_gain import DecisionGainEngine
from alpha.data_value_audit.feature_gap import FeatureGapEngine
from alpha.data_value_audit.information_gain import InformationGainEngine
from alpha.data_value_audit.infrastructure_gain import InfrastructureGainEngine
from alpha.data_value_audit.models import (
    DVRA_VERSION,
    ComplexityLevel,
    ConfidenceLevel,
    CostAssessment,
    CostStatus,
    DatasetCandidate,
    DatasetReportCard,
    DataValueAuditReport,
    ImpactLevel,
    ReplayImpact,
    RiskLevel,
    ROIClass,
)
from alpha.data_value_audit.replay_gain import ReplayGainEngine

_IMPACT_POINTS = {
    ImpactLevel.HIGH: 100,
    ImpactLevel.MEDIUM: 60,
    ImpactLevel.LOW: 25,
    ImpactLevel.UNKNOWN: 0,
}
_COMPLEXITY_BURDEN = {
    ComplexityLevel.LOW: 3,
    ComplexityLevel.MEDIUM: 8,
    ComplexityLevel.HIGH: 14,
}
_RISK_BURDEN = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 5,
    RiskLevel.HIGH: 10,
    RiskLevel.UNKNOWN: 8,
}


class DataValueROIEngine:
    """Assess candidates using a reproducible non-financial ROI rubric."""

    def __init__(self) -> None:
        self._information = InformationGainEngine()
        self._decision = DecisionGainEngine()
        self._infrastructure = InfrastructureGainEngine()
        self._replay = ReplayGainEngine()
        self._feature = FeatureGapEngine()
        self._cost = CostModel()

    def assess(self, candidate: DatasetCandidate) -> DatasetReportCard:
        information = self._information.assess(candidate)
        decision = self._decision.assess(candidate)
        infrastructure = self._infrastructure.assess(candidate)
        replay = self._replay.assess(candidate)
        feature = self._feature.assess(candidate)
        cost = self._cost.assess(candidate)
        replay_score = _replay_score(replay.impacts)
        gross = round(
            information.score * 0.35
            + decision.score * 0.30
            + infrastructure.score * 0.20
            + replay_score * 0.15
        )
        priority = _priority_index(gross, cost)
        roi_class = _roi_class(priority)
        confidence = _roi_confidence(cost.status, information.confidence, priority)
        rationale = (
            f"Gross decision value {gross}/100 from explicit evidence rubrics. "
            + (
                f"Cost-adjusted priority index {priority}/100; this is not a "
                "financial-return forecast."
                if priority is not None
                else "Overall cost-adjusted ROI remains UNKNOWN because no "
                "comparable standalone price is established."
            )
        )
        return DatasetReportCard(
            candidate=candidate,
            information=information,
            decision=decision,
            infrastructure=infrastructure,
            replay=replay,
            feature_gap=feature,
            cost=cost,
            gross_value_score=gross,
            priority_index=priority,
            roi_class=roi_class,
            roi_confidence=confidence,
            overall_rationale=rationale,
        )

    def report(self, candidates: tuple[DatasetCandidate, ...]) -> DataValueAuditReport:
        from alpha.data_value_audit.dependency_analysis import DependencyAnalysisEngine
        from alpha.data_value_audit.prioritization import ProcurementPrioritizer

        cards = tuple(self.assess(candidate) for candidate in candidates)
        dependencies = DependencyAnalysisEngine()
        return DataValueAuditReport(
            version=DVRA_VERSION,
            cards=cards,
            dependencies=dependencies.edges(candidates),
            sensitivity=dependencies.sensitivity(cards),
            budgets=ProcurementPrioritizer().plans(cards),
            methodology=(
                "Scores are ordinal research priorities. Replay effects are "
                "categorical, unknown prices remain unknown, and no CAGR, Sharpe, "
                "drawdown, precision, "
                "or financial ROI uplift is forecast."
            ),
        )


def _replay_score(impacts: tuple[ReplayImpact, ...]) -> int:
    known = tuple(
        _IMPACT_POINTS[item.impact]
        for item in impacts
        if item.impact is not ImpactLevel.UNKNOWN
    )
    return round(sum(known) / len(known)) if known else 0


def _priority_index(gross: int, cost: CostAssessment) -> int | None:
    status = cost.status
    if status not in {CostStatus.PUBLISHED, CostStatus.NO_LICENSE_FEE_IDENTIFIED}:
        return None
    annual = cost.annual_cost_inr
    if annual is None:
        return None
    acquisition_burden = (
        0
        if annual == 0
        else 8
        if annual <= 100_000
        else 16
        if annual <= 500_000
        else 25
    )
    burden = (
        acquisition_burden
        + _COMPLEXITY_BURDEN[cost.engineering_cost]
        + _COMPLEXITY_BURDEN[cost.maintenance_cost]
        + _RISK_BURDEN[cost.licensing_risk]
        + _RISK_BURDEN[cost.legal_risk]
    )
    return max(0, min(100, gross - burden))


def _roi_class(priority: int | None) -> ROIClass:
    if priority is None:
        return ROIClass.UNKNOWN
    if priority >= 60:
        return ROIClass.HIGH
    if priority >= 40:
        return ROIClass.MEDIUM
    return ROIClass.LOW


def _roi_confidence(
    cost_status: CostStatus,
    information_confidence: ConfidenceLevel,
    priority: int | None,
) -> ConfidenceLevel:
    if priority is None:
        return ConfidenceLevel.INSUFFICIENT
    if cost_status is CostStatus.NO_LICENSE_FEE_IDENTIFIED:
        return ConfidenceLevel.MEDIUM
    if information_confidence is ConfidenceLevel.HIGH:
        return ConfidenceLevel.HIGH
    return ConfidenceLevel.MEDIUM


__all__ = ["DataValueROIEngine"]
