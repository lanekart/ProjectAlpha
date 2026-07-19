from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.candidate_generation_research.models import CandidateResearchReport
from alpha.candidate_generation_research.pine_trade_import import chart_line_mapping


def render_executive_report(report: CandidateResearchReport) -> str:
    summary = report.summary
    blocker_counts = Counter(item.primary_blocker for item in report.missed_attribution)
    timing_counts = Counter(item.classification.value for item in report.timing_metrics)
    lines = [
        "# Tradable Opportunity Definition & Candidate Generation Recovery",
        "",
        f"**Canonical parent:** {report.manifest.parent_policy_id}  ",
        f"**Research policy:** {report.manifest.policy_id}  ",
        "**Production influence:** false",
        "",
        "## Executive Answer",
        "",
        f"- Forward move events: {summary.forward_move_events:,}",
        "- Events with a point-in-time tradable onset: "
        f"{summary.tradable_event_count:,}",
        f"- Point-in-time onsets linked to outcomes: {summary.tradable_onsets:,}",
        "- Future moves actually tradable: "
        f"{_percent(summary.future_moves_actually_tradable_share)}",
        "- Median onset-to-peak delay: "
        f"{_number(summary.median_onset_to_peak_sessions)} sessions",
        "- Median event adverse excursion before peak: "
        f"{_percent(summary.median_pre_entry_mae)}",
        f"- Median prospective reward/risk: {_number(summary.median_prospective_rr)}R",
        f"- Canonical setup recall: {_percent(summary.canonical_setup_recall)}",
        f"- Canonical candidate recall: {_percent(summary.canonical_candidate_recall)}",
        f"- Median candidate delay: {_number(summary.median_candidate_delay)} sessions",
        f"- Best validated variant: {summary.best_validated_variant}",
        f"- Candidate explosion risk: {summary.candidate_explosion_risk}",
        "",
        "Future return is used only as an outcome label. Every onset input is frozen "
        "at or before its onset date.",
        "",
        "## Primary Attribution",
        "",
    ]
    lines.extend(
        f"- {reason}: {count:,}" for reason, count in blocker_counts.most_common(8)
    )
    lines.extend(("", "## Timing", ""))
    lines.extend(
        f"- {reason}: {count:,}" for reason, count in timing_counts.most_common()
    )
    lines.extend(
        (
            "",
            "## Validation",
            "",
            "Variant selection used development and validation only. Holdout was not "
            "used to choose the winner.",
        )
    )
    for validation_row in report.validations:
        lines.append(
            f"- {validation_row.variant_id}: {validation_row.status.value}; "
            f"{validation_row.reason}"
        )
    lines.extend(("", "## Mandatory Cases", ""))
    for case_row in report.case_studies:
        lines.append(
            f"- {case_row.requested_symbol}: {case_row.coverage_classification}; "
            f"{case_row.primary_reason}"
        )
    lines.extend(("", "## Pine Integrity", ""))
    if not report.pine_logical_trades:
        lines.append(
            "- No trade-level TradingView CSV was supplied; parity remains unavailable."
        )
    else:
        issues = Counter(item.issue for item in report.pine_logical_trades)
        lines.extend(f"- {key}: {value:,}" for key, value in issues.most_common())
    lines.extend(("", "Chart line mapping:"))
    lines.extend(f"- {color}: {label}" for color, label in chart_line_mapping().items())
    lines.extend(
        (
            "",
            "## Guardrails",
            "",
            "- `PRODUCTION_INFLUENCE=false`",
            "- `NO_AUTOMATIC_DEPLOYMENT=true`",
            "- `NO_APPROVAL_RELAXATION=true`",
            "- `NO_WEIGHT_CHANGES=true`",
            "- `NO_FUTURE_LEAKAGE=true`",
            "- `POINT_IN_TIME_ONLY=true`",
            "- `HOLDOUT_REQUIRED=true`",
            "- `CANDIDATE_EXPLOSION_PENALTY=true`",
            "- `LEGACY_DATA_IS_PROVISIONAL=true`",
            "- `TRADINGVIEW_IS_SECONDARY_VALIDATOR=true`",
        )
    )
    return "\n".join(lines) + "\n"


def render_summary(report: CandidateResearchReport) -> str:
    summary = report.summary
    return (
        "\n".join(
            (
                "Tradable Opportunity & Candidate Recovery",
                f"Forward Move Events: {summary.forward_move_events}",
                f"Tradable Events: {summary.tradable_event_count}",
                "Tradable Share: "
                f"{_percent(summary.future_moves_actually_tradable_share)}",
                f"Canonical Setup Recall: {_percent(summary.canonical_setup_recall)}",
                "Canonical Candidate Recall: "
                f"{_percent(summary.canonical_candidate_recall)}",
                "Median Candidate Delay: "
                f"{_number(summary.median_candidate_delay)} sessions",
                f"Best Validated Variant: {summary.best_validated_variant}",
                "PRODUCTION_INFLUENCE=false",
            )
        )
        + "\n"
    )


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value * Decimal('100'):.2f}%"


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}"


__all__ = ["render_executive_report", "render_summary"]
