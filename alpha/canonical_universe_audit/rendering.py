from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.canonical_universe_audit.models import CanonicalUniverseAuditReport


def render_run_summary(report: CanonicalUniverseAuditReport) -> str:
    summary = report.executive
    return (
        "\n".join(
            (
                "Alpha Canonical Universe Opportunity Audit",
                _labels(report),
                f"Audit ID: {report.audit_id}",
                f"Canonical Engine: {report.canonical_engine_version}",
                f"Sessions Audited: {summary.total_sessions}",
                f"Universe Symbols: {report.dataset.symbols}",
                f"Technical Candidates: {summary.total_candidates}",
                f"Scored Candidates: {summary.scored_candidates}",
                f"Approval Candidates: {summary.total_approval_candidates}",
                f"Institutional Approvals: {summary.total_institutional_approvals}",
                f"Portfolio Eligible: {summary.total_portfolio_eligible}",
                (
                    "Canonical Runtime Failure Days: "
                    f"{summary.canonical_runtime_failure_days}"
                ),
                f"Production Influence: {str(report.production_influence).lower()}",
            )
        )
        + "\n"
    )


def render_opportunities(report: CanonicalUniverseAuditReport) -> str:
    summary = report.executive
    return (
        "\n".join(
            (
                "ACU Opportunity Capacity",
                _labels(report),
                f"Average Opportunities / Day: {summary.average_opportunities_per_day}",
                f"Median Opportunities / Day: {summary.median_opportunities_per_day}",
                f"Maximum Opportunities / Day: {summary.maximum_opportunities_per_day}",
                "Average Opportunities / Month: "
                f"{summary.average_opportunities_per_month}",
                "Maximum Opportunities / Month: "
                f"{summary.maximum_opportunities_per_month}",
                "Average Opportunities / Week: "
                f"{summary.average_opportunities_per_week}",
                "Average Opportunities / Year: "
                f"{summary.average_opportunities_per_year}",
                f"Zero-Opportunity Days: {summary.zero_opportunity_days}",
                f"One-Opportunity Days: {summary.one_opportunity_days}",
                f"Two-Plus Opportunity Days: {summary.two_plus_opportunity_days}",
                f"Five-Plus Opportunity Days: {summary.five_plus_opportunity_days}",
                f"Raw Simultaneous Approvals: {summary.raw_simultaneous_approvals}",
                (
                    "Estimated Independent Approvals: "
                    f"{summary.independent_simultaneous_approvals}"
                ),
            )
        )
        + "\n"
    )


def render_sectors(report: CanonicalUniverseAuditReport, *, limit: int = 20) -> str:
    lines = ["ACU Sector Opportunities", _labels(report)]
    ranked = sorted(
        report.sectors,
        key=lambda item: (-item.approved_opportunities, -item.candidates, item.sector),
    )[:limit]
    if not ranked:
        lines.append("No sector observations available.")
    for index, item in enumerate(ranked, start=1):
        lines.append(
            f"{index}. {item.sector}: candidates={item.candidates}, "
            f"approved={item.approved_opportunities}, "
            f"win_rate={_metric(item.win_rate)}, "
            f"payoff={_metric(item.average_realized_return_pct)}"
        )
    lines.append(
        "Industry, theme, and market-cap classifications are unavailable in the "
        "legacy dataset."
    )
    return "\n".join(lines) + "\n"


def render_gates(report: CanonicalUniverseAuditReport, *, limit: int = 20) -> str:
    counts = Counter(item.gate_code for item in report.gates if item.primary)
    category_counts = Counter(item.category.value for item in report.gates)
    lines = ["ACU Rejection Gate Attribution", _labels(report), "Primary Gates:"]
    for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
        :limit
    ]:
        lines.append(f"- {code}: {count}")
    if not counts:
        lines.append("- No rejection gates observed.")
    lines.append("Categories:")
    for category, count in sorted(
        category_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"- {category}: {count}")
    return "\n".join(lines) + "\n"


def render_liquidity(report: CanonicalUniverseAuditReport, *, limit: int = 20) -> str:
    ranked = sorted(
        report.liquidity,
        key=lambda item: (
            -(item.average_daily_turnover or Decimal("0")),
            item.symbol,
        ),
    )[:limit]
    lines = [
        "ACU Liquidity Capacity",
        _labels(report),
        "All capacity values are APPROXIMATE / LEGACY DATA at 1% of average turnover.",
    ]
    for index, item in enumerate(ranked, start=1):
        lines.append(
            f"{index}. {item.symbol}: bucket={item.liquidity_bucket.value}, "
            f"ADV={_money(item.average_daily_turnover)}, "
            f"1% capacity={_money(item.deployable_at_10_crore)}"
        )
    lines.append("Free float and live spread are unavailable.")
    return "\n".join(lines) + "\n"


def render_capacity(report: CanonicalUniverseAuditReport) -> str:
    summary = report.executive
    return (
        "\n".join(
            (
                "ACU Portfolio Capacity Estimate",
                _labels(report),
                "Reference Capital: INR 1,00,00,000",
                f"Average Invested: {summary.average_invested_percent}%",
                f"Average Idle: {summary.average_idle_percent}%",
                f"Average Positions: {summary.average_positions}",
                "Method: positive current portfolio eligibility, capped at 10% per "
                "position and 1% of legacy average traded value.",
                "Classification: APPROXIMATE / LEGACY DATA",
            )
        )
        + "\n"
    )


def render_executive_report(report: CanonicalUniverseAuditReport) -> str:
    summary = report.executive
    dataset_line = (
        f"- Dataset: {report.dataset.rows:,} rows, "
        f"{report.dataset.symbols:,} symbols, {report.dataset.sessions:,} sessions"
    )
    coverage_line = (
        f"- Coverage: {report.dataset.first_session.isoformat()} to "
        f"{report.dataset.last_session.isoformat()}"
    )
    score_counts = (
        f"{summary.score_80_plus:,} / {summary.score_90_plus:,} / "
        f"{summary.score_95_plus:,}"
    )
    approval_counts = (
        f"{summary.raw_simultaneous_approvals:,} / "
        f"{summary.independent_simultaneous_approvals:,}"
    )
    weekly_stats = (
        f"{summary.average_opportunities_per_week} / "
        f"{summary.median_opportunities_per_week} / "
        f"{summary.maximum_opportunities_per_week}"
    )
    yearly_stats = (
        f"{summary.average_opportunities_per_year} / "
        f"{summary.median_opportunities_per_year} / "
        f"{summary.maximum_opportunities_per_year}"
    )
    symbol_trade_stats = (
        f"{summary.average_trades_per_symbol} / {summary.median_trades_per_symbol}"
    )
    cluster_stats = (
        f"{summary.opportunity_day_clusters} / {summary.longest_opportunity_day_streak}"
    )
    monthly_lines = "\n".join(
        f"| {item.month} | {item.total_opportunities} | "
        f"{item.average_opportunities_per_day} | {item.maximum_opportunities} | "
        f"{item.heat.value} |"
        for item in report.monthly
    )
    top_symbols = "\n".join(
        f"| {index} | {item.symbol} | {item.candidate_count} | "
        f"{item.approval_count} | {item.portfolio_eligible_count} | "
        f"{item.average_score or 'unavailable'} |"
        for index, item in enumerate(report.symbols[:100], start=1)
    )
    gate_counts = Counter(item.gate_code for item in report.gates if item.primary)
    gates = "\n".join(
        f"| {code} | {count} |"
        for code, count in sorted(
            gate_counts.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return f"""# Alpha Canonical Universe Opportunity Audit

**PROVISIONAL / NOT AUTHORITATIVE / LEGACY_DATASET**

- Audit ID: `{report.audit_id}`
- Canonical engine: `{report.canonical_engine_version}`
- Production influence: `false`
{dataset_line}
{coverage_line}
- Dataset confidence: {report.dataset.confidence * Decimal("100")}%
- Sector metadata rows: {report.dataset.sector_rows:,}

## Executive Dashboard

| Measure | Result |
|---|---:|
| Sessions audited | {summary.total_sessions:,} |
| Technical candidates | {summary.total_candidates:,} |
| Candidates with final scores | {summary.scored_candidates:,} |
| Approval candidates | {summary.total_approval_candidates:,} |
| Institutional approvals | {summary.total_institutional_approvals:,} |
| Portfolio eligible | {summary.total_portfolio_eligible:,} |
| Canonical runtime failure days | {summary.canonical_runtime_failure_days:,} |
| Average opportunities/day | {summary.average_opportunities_per_day} |
| Median opportunities/day | {summary.median_opportunities_per_day} |
| Maximum opportunities/day | {summary.maximum_opportunities_per_day} |
| Average opportunities/month | {summary.average_opportunities_per_month} |
| Average / median / max opportunities/week | {weekly_stats} |
| Average / median / max opportunities/year | {yearly_stats} |
| Zero-opportunity days | {summary.zero_opportunity_days:,} |
| Five-plus opportunity days | {summary.five_plus_opportunity_days:,} |
| Average invested capital | {summary.average_invested_percent}% |
| Average idle capital | {summary.average_idle_percent}% |
| Average positions | {summary.average_positions} |
| Average / median trades per symbol | {symbol_trade_stats} |
| Opportunity-day clusters / longest streak | {cluster_stats} |
| Average candidate score | {_metric(summary.average_score)} |
| Median candidate score | {_metric(summary.median_score)} |
| Scores 80+ / 90+ / 95+ | {score_counts} |
| Largest primary gate | {summary.largest_gate} ({summary.largest_gate_rejections:,}) |
| Raw / independent approvals | {approval_counts} |
| Completed trade-plan outcomes | {summary.completed_outcomes:,} |
| Pending or not-entered outcomes | {summary.pending_outcomes:,} |
| Win rate | {_metric(summary.win_rate)} |
| Average realized payoff | {_metric(summary.expected_payoff_pct)} |

## Opportunity Heatmap

| Month | Opportunities | Average/Day | Maximum | Heat |
|---|---:|---:|---:|---|
{monthly_lines}

## Rejection Gates

| Primary Gate | Rejections |
|---|---:|
{gates}

## Top 100 Symbols by Candidate Frequency

| Rank | Symbol | Candidates | Approval | Eligible | Average Score |
|---:|---|---:|---:|---:|---:|
{top_symbols}

## Capacity Interpretation

Capacity is an **APPROXIMATE / LEGACY DATA** diagnostic. It uses the current
Alpha capacity convention of 1% of average daily traded value. Free float,
bid/ask spread, industry, theme, and market-cap history are unavailable and are
not inferred. Candidate priorities are research ranks, not allocations.

## Evidence Boundary

This report measures the frozen current engine. It does not alter weights,
thresholds, approval rules, strategies, timing, stops, exits, trade plans,
learning, or adaptive-weight policy. Historical outcomes use the recorded plan,
explicit transaction-cost assumptions, and conservative stop-first ordering
when a stop and target occur in the same bar.
"""


def _labels(report: CanonicalUniverseAuditReport) -> str:
    return " / ".join(report.dataset.labels)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _money(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"INR {value:,.2f}"


__all__ = [
    "render_capacity",
    "render_executive_report",
    "render_gates",
    "render_liquidity",
    "render_opportunities",
    "render_run_summary",
    "render_sectors",
]
