from __future__ import annotations

from decimal import Decimal

from alpha.learning_intelligence.models import (
    AdaptiveLearningAssessment,
    AdaptiveLearningReport,
    FingerprintStatistics,
)


def render_learning_report(report: AdaptiveLearningReport) -> tuple[str, ...]:
    lines = [
        "Adaptive Learning Report",
        f"Total Completed Samples: {report.total_completed_samples}",
        "",
        "Strongest Fingerprints:",
    ]
    lines.extend(_stats_lines(report.strongest_fingerprints))
    lines.extend(("", "Weakest Fingerprints:"))
    lines.extend(_stats_lines(report.weakest_fingerprints))
    lines.extend(("", "Best-Performing Sectors:"))
    lines.extend(_breakdown_lines(report.sector_statistics))
    lines.extend(("", "Weakest Sectors:"))
    lines.extend(_breakdown_lines(report.sector_statistics, reverse=False))
    lines.extend(("", "Best-Performing Regimes:"))
    lines.extend(_breakdown_lines(report.regime_statistics))
    lines.extend(("", "Confidence Calibration Table:"))
    lines.extend(_breakdown_lines(report.confidence_statistics))
    lines.extend(("", "Feature Contribution Summary:"))
    if report.feature_contributions:
        for contribution in report.feature_contributions[:10]:
            lines.append(
                "- "
                f"{contribution.dimension}={contribution.value}: "
                f"expectancy={_decimal(contribution.average_expectancy)}, "
                f"stop_hit={_decimal(contribution.stop_hit_rate)}, "
                f"target_hit={_decimal(contribution.target_hit_rate)}, "
                f"samples={contribution.sample_count}"
            )
    else:
        lines.append("- unavailable")
    lines.extend(("", "Insufficient Sample Warnings:"))
    if report.insufficient_sample_warnings:
        lines.extend(
            f"- {warning}" for warning in report.insufficient_sample_warnings[:10]
        )
    else:
        lines.append("- none")
    return tuple(lines)


def render_learning_explain(
    *,
    symbol: str,
    assessment: AdaptiveLearningAssessment | None,
    missing_reason: str | None = None,
) -> tuple[str, ...]:
    lines = [f"Adaptive Learning Explain: {symbol.strip().upper()}"]
    if assessment is None:
        lines.append(missing_reason or "No recommendation evidence available.")
        return tuple(lines)
    stats = assessment.statistics
    bayesian = assessment.bayesian
    confidence = assessment.confidence
    lines.extend(
        (
            f"Fingerprint: {assessment.fingerprint.key}",
            f"Available Historical Evidence: {stats.completed_trade_count} completed "
            f"of {stats.sample_count} total samples",
            f"Evidence Strength: {stats.evidence_strength.value}",
            f"Prior Probability: {bayesian.prior_win_probability}",
            f"Posterior Probability: {bayesian.posterior_win_probability}",
            "Uncertainty Band: "
            f"{bayesian.lower_confidence_bound} to {bayesian.upper_confidence_bound}",
            f"Base Confidence: {confidence.base_confidence}",
            f"Adjusted Confidence: {confidence.adjusted_confidence}",
            f"Adjustment Reason: {confidence.adjustment_reason}",
            f"Expectancy: {_decimal(stats.expectancy)}",
            f"Average R: {_decimal(stats.average_r)}",
            f"Stop Hit Rate: {_decimal(stats.stop_hit_rate)}",
            f"Target 1 Hit Rate: {_decimal(stats.target_1_hit_rate)}",
            "Missing Evidence: "
            + (
                "completed samples below reliability threshold"
                if stats.insufficient
                else "none"
            ),
        )
    )
    return tuple(lines)


def concise_adaptive_line(
    *,
    evidence_strength: str,
    adjusted_confidence: str,
    base_confidence: str,
    sample_count: int,
) -> str:
    if adjusted_confidence != base_confidence:
        confidence_text = f"adjusted confidence {adjusted_confidence}"
    else:
        confidence_text = "confidence unchanged"
    return (
        "   - Adaptive Evidence: "
        f"{evidence_strength}; {confidence_text}; samples={sample_count}"
    )


def _stats_lines(stats: tuple[FingerprintStatistics, ...]) -> list[str]:
    if not stats:
        return ["- unavailable"]
    return [
        "- "
        f"{stat.fingerprint.key}: expectancy={_decimal(stat.expectancy)}, "
        f"win={stat.win_count}, loss={stat.loss_count}, "
        f"samples={stat.completed_trade_count}, evidence={stat.evidence_strength.value}"
        for stat in stats
    ]


def _breakdown_lines(
    stats: dict[str, FingerprintStatistics] | object,
    *,
    reverse: bool = True,
) -> list[str]:
    items = tuple(getattr(stats, "items")())
    if not items:
        return ["- unavailable"]
    ordered = sorted(
        items,
        key=lambda item: (
            item[1].expectancy if item[1].expectancy is not None else Decimal("-999")
        ),
        reverse=reverse,
    )
    return [
        "- "
        f"{label}: expectancy={_decimal(stat.expectancy)}, "
        f"samples={stat.completed_trade_count}, evidence={stat.evidence_strength.value}"
        for label, stat in ordered[:5]
    ]


def _decimal(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "concise_adaptive_line",
    "render_learning_explain",
    "render_learning_report",
]
