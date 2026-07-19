from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.continuous_learning.models import (
    CollectionSummary,
    ConfidenceCalibrationReport,
    ContinuousLearningReport,
    DriftAssessment,
    OutcomeObservation,
    ResearchRecommendation,
    StrategyHealth,
)


def render_collection(summary: CollectionSummary) -> tuple[str, ...]:
    return (
        "Continuous Learning Collection",
        f"Current Source Recommendations: {summary.recommendations_seen}",
        f"Permanent Registry Recommendations: {summary.registry_recommendations}",
        "Retained Historical Recommendations: "
        f"{summary.retained_historical_recommendations}",
        f"Observations Generated: {summary.observations_generated}",
        f"New Immutable Observations: {summary.observations_inserted}",
        f"New Learning Events: {summary.learning_events_inserted}",
        f"Pending / Active: {summary.pending_count}",
        f"Completed: {summary.completed_count}",
        f"Missing Data: {summary.missing_data_count}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_outcomes(
    outcomes: tuple[OutcomeObservation, ...],
    *,
    analytically_eligible_recommendations: int | None = None,
    quarantined_recommendations: int = 0,
) -> tuple[str, ...]:
    counts = Counter(item.status.value for item in outcomes)
    completed = tuple(item for item in outcomes if item.realised_return_pct is not None)
    lines = [
        "Continuous Learning Outcomes",
        f"Permanent Registry Recommendations: {len(outcomes)}",
    ]
    if analytically_eligible_recommendations is not None:
        lines.extend(
            (
                "Analytically Eligible Recommendations: "
                f"{analytically_eligible_recommendations}",
                "Quarantined Historical Recommendations: "
                f"{quarantined_recommendations}",
            )
        )
    lines.extend(
        [
            f"Resolved Registry Returns: {len(completed)}",
            "Outcome Status:",
        ]
    )
    lines.extend(f"- {name}: {count}" for name, count in sorted(counts.items()))
    lines.append("Latest Resolved Outcomes:")
    if not completed:
        lines.append("- unavailable; no resolved realised returns")
    else:
        lines.extend(
            f"- {item.symbol}: {item.status.value}; return="
            f"{_number(item.realised_return_pct)}%; MFE={_number(item.mfe_pct)}%; "
            f"MAE={_number(item.mae_pct)}%; holding={item.holding_period_days} days"
            for item in completed[-10:]
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_drift(drifts: tuple[DriftAssessment, ...]) -> tuple[str, ...]:
    lines = ["Continuous Learning Drift Report"]
    for item in drifts:
        lines.append(
            f"- {item.dimension}: {item.status.value} | "
            f"earlier n={item.baseline_count}, "
            f"recent n={item.recent_count}, change={_number(item.absolute_change)} | "
            f"confidence={item.confidence.value}"
        )
        lines.append(f"  Evidence: {' '.join(item.evidence)}")
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_strategy_health(health: tuple[StrategyHealth, ...]) -> tuple[str, ...]:
    lines = ["Continuous Strategy Health"]
    if not health:
        lines.append("- no strategy observations")
    for item in health:
        lines.append(
            f"- {item.strategy_key}: {item.classification.value} | "
            f"completed={item.completed_count}/{item.sample_count}, "
            f"win rate={_number(item.win_rate_pct)}%, "
            f"expectancy={_number(item.expectancy_pct)}%, "
            f"health={_number(item.health_score)}, "
            f"confidence={item.confidence.value}"
        )
        lines.append(f"  Evidence: {'; '.join(item.evidence)}")
    lines.extend(
        (
            "No strategy is automatically retired or promoted.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_calibration(report: ConfidenceCalibrationReport) -> tuple[str, ...]:
    lines = [
        "Confidence Calibration",
        f"Status: {report.status}",
        f"Completed Predictions: {report.completed_predictions}",
        f"Brier Score: {_number(report.brier_score)}",
        f"Expected Calibration Error: {_number(report.expected_calibration_error)}",
        f"Evidence Confidence: {report.confidence.value}",
        "Reliability Buckets:",
    ]
    if not report.buckets:
        lines.append("- unavailable")
    lines.extend(
        f"- {item.confidence_label}: predicted={item.predicted_probability}; "
        f"observed={_number(item.observed_success_rate)}; n={item.sample_count}; "
        f"error={_number(item.calibration_error)}"
        for item in report.buckets
    )
    lines.append("Assumptions:")
    lines.extend(f"- {item}" for item in report.assumptions)
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_recommendations(
    recommendations: tuple[ResearchRecommendation, ...],
) -> tuple[str, ...]:
    lines = ["Continuous Learning Research Recommendations"]
    if not recommendations:
        lines.append("- No evidence-supported research trigger is active.")
    for item in recommendations:
        lines.extend(
            (
                f"- {item.priority} | {item.title}",
                f"  Subsystem: {item.subsystem}",
                f"  Evidence: {item.evidence_summary}",
                f"  Evidence IDs: {', '.join(item.evidence_ids)}",
                f"  Recommendation: {item.recommended_research}",
                f"  Confidence: {item.confidence.value}",
            )
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_learning_report(report: ContinuousLearningReport) -> tuple[str, ...]:
    drift_order = {
        "SIGNIFICANT_DRIFT": 0,
        "EARLY_DRIFT": 1,
        "NO_DRIFT": 2,
        "UNKNOWN": 3,
    }
    largest = min(
        report.drifts,
        key=lambda item: (drift_order[item.status.value], item.dimension),
        default=None,
    )
    health_counts = Counter(
        item.classification.value for item in report.strategy_health
    )
    lines = [
        "Executive Continuous Learning Report",
        f"Evidence Timestamp: {report.generated_at.isoformat()}",
        f"Latest Evidence-Date Recommendations: {report.todays_recommendations}",
        f"Tracked Recommendations: {len(report.outcomes)}",
        "Analytically Eligible Recommendations: "
        f"{report.analytically_eligible_recommendations}",
        f"Quarantined Historical Recommendations: {report.quarantined_recommendations}",
        f"Resolved Predictions: {report.calibration.completed_predictions}",
        "Current Strategy Health:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(health_counts.items()))
    lines.extend(
        (
            "Largest Drift: "
            + (
                "unavailable"
                if largest is None
                else f"{largest.dimension} — {largest.status.value}"
            ),
            f"Calibration Status: {report.calibration.status}",
            f"Confidence Trend: {report.confidence_trend}",
            f"Deployment Status: {report.deployment_status}",
            f"Overall Learning Confidence: {report.overall_learning_confidence.value}",
            "Research Recommendations:",
        )
    )
    lines.extend(
        f"- {item.priority}: {item.title} — {item.recommended_research}"
        for item in report.research_recommendations
    )
    lines.extend(
        (
            "No confidence, strategy, approval, allocation, or execution value "
            "was changed.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "render_calibration",
    "render_collection",
    "render_drift",
    "render_learning_report",
    "render_outcomes",
    "render_recommendations",
    "render_strategy_health",
]
