from __future__ import annotations

from alpha.benchmark_replay.models import BenchmarkReplayReport


def render_executive_report(report: BenchmarkReplayReport) -> str:
    manifest = report.manifest
    stats = report.portfolio_statistics
    flow = report.candidate_statistics
    opportunity = next(
        (
            item
            for item in report.opportunity_capture
            if item.opportunity_definition == "ALL"
        ),
        None,
    )
    approvals = sum(item.institutional_approvals for item in flow)
    candidates = sum(item.technical_candidates for item in flow)
    buy = sum(item.buy_candidates for item in flow)
    strong_buy = sum(item.strong_buy_candidates for item in flow)
    capture_rate = None if opportunity is None else opportunity.capture_rate_percent
    lines = [
        "# Canonical Alpha Benchmark Replay",
        "",
        f"**{manifest.baseline_id} / {manifest.replay_classification}**",
        "",
        f"- Replay window: {manifest.replay_start} to {manifest.replay_end}",
        f"- Sessions: {manifest.sessions:,}",
        f"- Universe: {manifest.universe_label}",
        f"- Historical index membership: {manifest.historical_index_membership}",
        f"- Historical sector membership: {manifest.historical_sector_membership}",
        f"- Point-in-time enforced: {str(manifest.point_in_time_enforced).lower()}",
        f"- Production influence: {str(manifest.production_influence).lower()}",
        "",
        "## Executive Result",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Eligible securities | {report.eligible_securities:,} |",
        f"| Eligible security-days | {report.eligible_security_observations:,} |",
        f"| Technical candidates | {candidates:,} |",
        f"| BUY candidates | {buy:,} |",
        f"| STRONG BUY candidates | {strong_buy:,} |",
        f"| Institutional approvals | {approvals:,} |",
        f"| Trades executed | {stats.logical_trades:,} |",
        f"| Win rate | {_value(stats.win_rate_percent, '%')} |",
        f"| Profit factor | {_value(stats.profit_factor)} |",
        f"| Expectancy | {_value(stats.expectancy_percent, '%')} |",
        f"| CAGR | {stats.cagr_percent}% |",
        f"| Maximum drawdown | {stats.maximum_drawdown_percent}% |",
        f"| Sharpe | {_value(stats.sharpe_ratio)} |",
        f"| Sortino | {_value(stats.sortino_ratio)} |",
        f"| Calmar | {_value(stats.calmar_ratio)} |",
        "| Average capital utilisation | "
        f"{stats.average_capital_utilisation_percent}% |",
        f"| Average idle cash | INR {stats.average_idle_cash} |",
        f"| Opportunity capture | {_value(capture_rate, '%')} |",
        "",
        "## Portfolio",
        "",
        f"Starting capital was INR {stats.starting_capital}; ending capital was "
        f"INR {stats.ending_capital}. The unchanged institutional gate approved "
        f"{approvals} candidates, so capital deployment reflects policy output "
        "rather than a relaxed or counterfactual strategy.",
        "",
        "## Trading Statistics",
        "",
        f"- Winners / losers / breakeven: {stats.winning_trades} / "
        f"{stats.losing_trades} / {stats.breakeven_trades}",
        f"- Average winner: {_value(stats.average_winner_percent, '%')}",
        f"- Average loser: {_value(stats.average_loser_percent, '%')}",
        f"- Median holding period: {_value(stats.median_holding_period_days, ' days')}",
        f"- Turnover: {stats.turnover_percent}%",
        "",
        "## Rejection Attribution",
        "",
    ]
    if report.top_rejection_reasons:
        lines.extend(
            f"- {code}: {count:,}" for code, count in report.top_rejection_reasons
        )
    else:
        lines.append("- No rejected candidates were recorded.")
    lines.extend(("", "## Benchmark Comparison", ""))
    for item in report.benchmark_comparison:
        lines.append(
            f"- **{item.benchmark}**: {item.availability.value}; "
            f"CAGR {_value(item.cagr_percent, '%')}. {item.reason}"
        )
    lines.extend(("", "## Scientific Boundary", ""))
    lines.extend(f"- {note}" for note in manifest.notes)
    lines.extend(
        (
            "",
            "This report is the fixed comparison point for future Alpha research. "
            "It does not recommend policy promotion or capital deployment.",
            "",
            "**PRODUCTION_INFLUENCE=false**",
            "",
        )
    )
    return "\n".join(lines)


def render_replay_summary(report: BenchmarkReplayReport) -> str:
    stats = report.portfolio_statistics
    candidates = sum(item.technical_candidates for item in report.candidate_statistics)
    approvals = sum(
        item.institutional_approvals for item in report.candidate_statistics
    )
    return "\n".join(
        (
            "Canonical Alpha Benchmark Replay",
            f"Baseline: {report.manifest.baseline_id}",
            f"Classification: {report.manifest.replay_classification}",
            f"Sessions: {report.manifest.sessions}",
            f"Technical Candidates: {candidates}",
            f"Institutional Approvals: {approvals}",
            f"Trades Executed: {stats.logical_trades}",
            f"Ending Capital: INR {stats.ending_capital}",
            f"CAGR: {stats.cagr_percent}%",
            f"Maximum Drawdown: {stats.maximum_drawdown_percent}%",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _value(value: object | None, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{value}{suffix}"


__all__ = ["render_executive_report", "render_replay_summary"]
