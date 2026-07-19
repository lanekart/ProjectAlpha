from __future__ import annotations

from hashlib import sha256

from alpha.continuous_learning.models import (
    ConfidenceCalibrationReport,
    DriftAssessment,
    DriftStatus,
    LearningConfidence,
    ResearchRecommendation,
    StrategyHealth,
    StrategyHealthClassification,
)


class ResearchTriggerEngine:
    """Generate evidence-referenced research work, never policy changes."""

    def recommend(
        self,
        *,
        drifts: tuple[DriftAssessment, ...],
        health: tuple[StrategyHealth, ...],
        calibration: ConfidenceCalibrationReport,
    ) -> tuple[ResearchRecommendation, ...]:
        recommendations: list[ResearchRecommendation] = []
        for drift in drifts:
            if drift.status in {DriftStatus.EARLY_DRIFT, DriftStatus.SIGNIFICANT_DRIFT}:
                recommendations.append(
                    _recommendation(
                        priority="P0"
                        if drift.status is DriftStatus.SIGNIFICANT_DRIFT
                        else "P1",
                        subsystem=drift.dimension,
                        title=(
                            f"Investigate "
                            f"{drift.dimension.replace('_', ' ').title()} drift"
                        ),
                        evidence_ids=(drift.drift_id,),
                        evidence_summary="; ".join(drift.evidence),
                        research=(
                            "Run a point-in-time cohort attribution study before "
                            "proposing "
                            "any threshold or strategy change."
                        ),
                        confidence=drift.confidence,
                    )
                )
        for item in health:
            if item.classification in {
                StrategyHealthClassification.DEGRADING,
                StrategyHealthClassification.RETIRE,
            }:
                recommendations.append(
                    _recommendation(
                        priority="P0",
                        subsystem="STRATEGY_HEALTH",
                        title=f"Review {item.strategy_key} strategy deterioration",
                        evidence_ids=(f"strategy-health-{item.strategy_key}",),
                        evidence_summary="; ".join(item.evidence),
                        research=(
                            "Perform outcome attribution, parameter stability, and "
                            "walk-forward revalidation. Do not retire automatically."
                        ),
                        confidence=item.confidence,
                    )
                )
        if calibration.status in {
            "CALIBRATION_WATCH",
            "SIGNIFICANT_MISCALIBRATION",
        }:
            recommendations.append(
                _recommendation(
                    priority=(
                        "P0"
                        if calibration.status == "SIGNIFICANT_MISCALIBRATION"
                        else "P1"
                    ),
                    subsystem="CONFIDENCE_CALIBRATION",
                    title="Investigate confidence reliability",
                    evidence_ids=("confidence-calibration",),
                    evidence_summary=(
                        f"completed={calibration.completed_predictions}; "
                        f"Brier={calibration.brier_score}; "
                        f"ECE={calibration.expected_calibration_error}"
                    ),
                    research=(
                        "Validate confidence mappings on larger frozen cohorts before "
                        "considering any production recalibration."
                    ),
                    confidence=calibration.confidence,
                )
            )
        if not recommendations and (
            calibration.confidence is LearningConfidence.INSUFFICIENT
            or all(item.status is DriftStatus.UNKNOWN for item in drifts)
        ):
            recommendations.append(
                _recommendation(
                    priority="P0",
                    subsystem="FORWARD_EVIDENCE",
                    title="Mature immutable forward outcome evidence",
                    evidence_ids=("forward-outcome-sample",),
                    evidence_summary=(
                        f"Only {calibration.completed_predictions} resolved "
                        "predictions "
                        "are eligible for confidence calibration."
                    ),
                    research=(
                        "Continue outcome collection and resolve entry, exit, MFE, "
                        "MAE, "
                        "volatility, liquidity, regime, and sector evidence."
                    ),
                    confidence=LearningConfidence.HIGH,
                )
            )
        return tuple(
            sorted(
                recommendations,
                key=lambda item: (
                    item.priority,
                    item.subsystem,
                    item.recommendation_id,
                ),
            )
        )


def _recommendation(
    *,
    priority: str,
    subsystem: str,
    title: str,
    evidence_ids: tuple[str, ...],
    evidence_summary: str,
    research: str,
    confidence: LearningConfidence,
) -> ResearchRecommendation:
    identity = sha256(
        f"{priority}|{subsystem}|{title}|{'|'.join(evidence_ids)}".encode()
    ).hexdigest()[:20]
    return ResearchRecommendation(
        recommendation_id=f"cll-research-{identity}",
        priority=priority,
        subsystem=subsystem,
        title=title,
        evidence_ids=evidence_ids,
        evidence_summary=evidence_summary,
        recommended_research=research,
        confidence=confidence,
    )


__all__ = ["ResearchTriggerEngine"]
