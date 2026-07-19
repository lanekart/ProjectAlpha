from __future__ import annotations

from decimal import Decimal

from alpha.candidate_learning.models import LearningSummary
from alpha.candidate_learning.raw_universe import RawUniverseLearningSummary


def render_learning_summary(summary: LearningSummary) -> tuple[str, ...]:
    lines = [
        "Candidate Learning Summary",
        f"Period: {summary.period}",
        f"Candidates Evaluated: {summary.total_candidates_evaluated}",
        f"Approved: {summary.approved_count}",
        f"Rejected: {summary.rejected_count}",
        f"Watchlist: {summary.watchlist_count}",
        f"Avoid: {summary.avoid_count}",
        f"Sell: {summary.sell_count}",
        f"Completed Forward Outcomes: {summary.completed_forward_windows}",
        f"False Positives: {summary.quality.false_positive_count}",
        f"False Negatives: {summary.quality.false_negative_count}",
        f"Correct Approvals: {summary.quality.correct_approval_count}",
        f"Correct Rejects: {summary.quality.correct_reject_count}",
        f"Approval Precision: {_metric(summary.quality.approval_precision)}",
        f"Rejection Accuracy: {_metric(summary.quality.rejection_accuracy)}",
        f"Missed Opportunity Rate: {_metric(summary.quality.missed_opportunity_rate)}",
        f"Data Gaps: {summary.data_gaps}",
        "",
        "Best Indicator Combinations:",
    ]
    lines.extend(_rank_lines(summary.best_indicator_combinations))
    lines.extend(("", "Worst Indicator Combinations:"))
    lines.extend(_rank_lines(summary.worst_indicator_combinations))
    lines.extend(("", "Best Setup/Regime Combinations:"))
    lines.extend(_rank_lines(summary.best_setup_regime_combinations))
    lines.extend(("", "Worst Setup/Regime Combinations:"))
    lines.extend(_rank_lines(summary.worst_setup_regime_combinations))
    if not summary.sufficient_sample:
        lines.append(
            "Learning summary: insufficient completed forward outcomes for "
            "statistical conclusions."
        )
    if summary.approved_count == 0:
        lines.extend(
            (
                "",
                "Institutional Deployment Status: NO DEPLOYABLE TRADE",
                "No high-quality trade setup qualifies for capital deployment "
                "under the current institutional policy.",
                "Historical approvals have not yet demonstrated sufficient "
                "precision and evidence quality to justify deployment.",
                "Zero approvals do not prove that no profitable setup existed; "
                "they mean no candidate met every current institutional requirement.",
                "Approval precision is unavailable because no approvals were emitted.",
            )
        )
    return tuple(lines)


def render_nightly_learning_report(
    *,
    records_checked: int,
    outcomes_updated: int,
    summary: LearningSummary,
    strategy_regime_status: str,
) -> tuple[str, ...]:
    return (
        "Nightly Learning Loop",
        f"Candidates Checked: {records_checked}",
        f"Forward Outcomes Updated: {outcomes_updated}",
        f"Strategy-Regime Backtests: {strategy_regime_status}",
        *render_learning_summary(summary),
    )


def render_raw_universe_summary(
    summary: RawUniverseLearningSummary,
) -> tuple[str, ...]:
    filter_value = (
        "Not yet computed"
        if summary.filter_value_added is None or not summary.sufficient_sample
        else f"{_signed(summary.filter_value_added)}%"
    )
    lines = [
        "Raw Universe Learning Summary",
        f"Total Raw Candidates Tracked: {summary.total_raw_candidates}",
        f"Emitted Decisions: {summary.emitted_decisions}",
        f"Non-Emitted Candidates: {summary.non_emitted_candidates}",
        f"False Negatives: {summary.false_negatives}",
        f"Correct Rejects: {summary.correct_rejects}",
        f"Missed Opportunity Rate: {_metric(summary.missed_opportunity_rate)}",
        f"Average Return Emitted: {_metric(summary.average_return_emitted)}",
        f"Average Return Non-Emitted: {_metric(summary.average_return_non_emitted)}",
        f"Filter Value Added: {filter_value}",
        f"Top Exclusion Stage: {summary.top_exclusion_stage}",
        f"Data Gaps: {summary.data_gaps}",
        "",
        "Best Filters:",
    ]
    lines.extend(_rank_lines(summary.best_filters))
    lines.extend(("", "Weakest Filters:"))
    lines.extend(_rank_lines(summary.weakest_filters))
    lines.extend(("", "Filter Quality by Stage/Reason:"))
    lines.extend(_filter_quality_lines(summary))
    if not summary.sufficient_sample:
        lines.append("Raw universe learning: Not yet computed; insufficient sample.")
    return tuple(lines)


def _rank_lines(items: tuple[tuple[str, Decimal], ...]) -> list[str]:
    if not items:
        return ["- unavailable"]
    return [f"- {name}: {_signed(value)}%" for name, value in items]


def _filter_quality_lines(summary: RawUniverseLearningSummary) -> list[str]:
    if not summary.filter_quality:
        return ["- unavailable"]
    lines: list[str] = []
    for item in summary.filter_quality[:10]:
        return_20d = dict(item.average_forward_returns).get("20d")
        lines.append(
            "- "
            f"{item.exclusion_stage} / {item.exclusion_reason}: "
            f"{item.candidates_excluded} excluded, "
            f"20d avg {_metric(return_20d)}, "
            f"false negatives {item.false_negative_count}, "
            f"correct rejects {item.correct_reject_count}"
        )
    return lines


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _signed(value: Decimal) -> str:
    return f"+{value}" if value > Decimal("0") else str(value)


__all__ = [
    "render_learning_summary",
    "render_nightly_learning_report",
    "render_raw_universe_summary",
]
