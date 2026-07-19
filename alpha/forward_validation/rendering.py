from __future__ import annotations

from decimal import Decimal

from alpha.forward_validation.models import (
    ApprovalOptimizationReport,
    DeploymentReadinessReport,
    ForwardPerformanceMetrics,
    ForwardUpdateSummary,
    ForwardValidationConfig,
    PolicyScorecard,
    PositionJournalRow,
    RecommendationSnapshot,
    ShadowPortfolioSnapshot,
)


def render_start(config: ForwardValidationConfig, *, created: bool) -> tuple[str, ...]:
    return (
        "Forward Validation",
        f"Status: {'STARTED' if created else 'ALREADY_INITIALIZED'}",
        f"Policy Cohort: {config.policy_version.value}",
        f"Initial Capital: {_money(config.initial_capital)}",
        "Evidence Mode: IMMUTABLE_FORWARD_ONLY",
        "Production Influence: false",
    )


def render_snapshot(
    snapshots: tuple[RecommendationSnapshot, ...],
    *,
    inserted: int,
) -> tuple[str, ...]:
    lines = [
        "Forward Recommendation Snapshot",
        f"Recommendations Frozen: {len(snapshots)}",
        f"New Immutable Records: {inserted}",
    ]
    for snapshot in snapshots:
        lines.extend(
            (
                "",
                f"{snapshot.symbol} — {snapshot.final_verdict}",
                f"  Snapshot ID: {snapshot.recommendation_id}",
                f"  Generated: {snapshot.generated_at.isoformat()}",
                f"  Price: {_money(snapshot.current_market_price)}",
                f"  Entry: {_zone(snapshot.entry_zone_low, snapshot.entry_zone_high)}",
                f"  Stop: {_money(snapshot.stop_loss)}",
                f"  Targets: {_targets(snapshot)}",
                f"  Policy: {snapshot.policy_version.value}",
                f"  Evidence Hash: {snapshot.snapshot_hash}",
            )
        )
    lines.append("Production Influence: false")
    return tuple(lines)


def render_update(summary: ForwardUpdateSummary) -> tuple[str, ...]:
    return (
        "Forward Portfolio Update",
        f"Recommendations Checked: {summary.recommendations_checked}",
        f"New Immutable Events: {summary.new_events}",
        f"Newly Entered: {summary.newly_entered}",
        f"Newly Exited: {summary.newly_exited}",
        f"Still Active: {summary.still_active}",
        f"Missing Data: {summary.missing_data_count}",
        "Production Influence: false",
    )


def render_portfolios(
    portfolios: tuple[ShadowPortfolioSnapshot, ...],
) -> tuple[str, ...]:
    lines = ["Shadow Portfolio"]
    for portfolio in portfolios:
        open_positions = sum(
            1 for item in portfolio.positions if item.status.value == "ACTIVE"
        )
        lines.extend(
            (
                "",
                f"Policy: {portfolio.policy_version.value}",
                f"Portfolio Value: {_money(portfolio.portfolio_value)}",
                f"Cash: {_money(portfolio.cash)}",
                f"Realized P/L: {_money(portfolio.realized_profit_loss)}",
                f"Unrealized P/L: {_money(portfolio.unrealized_profit_loss)}",
                f"Capital Utilization: {_percent(portfolio.capital_utilization_pct)}",
                f"Drawdown: {_percent(portfolio.drawdown_pct)}",
                f"Daily Loss: {_percent(portfolio.daily_loss_pct)}",
                f"Open Positions: {open_positions}",
            )
        )
        for position in portfolio.positions:
            last_price = (
                None
                if position.quantity == Decimal("0")
                and position.last_price == Decimal("0")
                else position.last_price
            )
            lines.append(
                f"  {position.symbol}: {position.status.value} | "
                f"Qty {position.quantity} | Last {_money(last_price)}"
            )
    lines.extend(
        ("", "No broker connection. No order execution.", "Production Influence: false")
    )
    return tuple(lines)


def render_performance(
    metrics: tuple[ForwardPerformanceMetrics, ...],
) -> tuple[str, ...]:
    lines = ["Forward Performance"]
    for item in metrics:
        lines.extend(
            (
                "",
                f"Policy: {item.policy_version.value}",
                f"Recommendations: {item.recommendation_count}",
                "Entered / Completed / Open: "
                f"{item.entered_count} / {item.completed_count} / {item.open_count}",
                f"Approval Precision: {_percent(item.approval_precision_pct)}",
                f"Win Rate: {_percent(item.win_rate_pct)}",
                f"Average Winner: {_percent(item.average_winner_pct)}",
                f"Average Loser: {_percent(item.average_loser_pct)}",
                f"Profit Factor: {_number(item.profit_factor)}",
                f"Expectancy: {_percent(item.expectancy_pct)}",
                "Sharpe / Sortino: "
                f"{_number(item.sharpe_ratio)} / {_number(item.sortino_ratio)}",
                f"Maximum Drawdown: {_percent(item.maximum_drawdown_pct)}",
                "Consecutive Wins / Losses: "
                f"{item.consecutive_wins} / {item.consecutive_losses}",
                f"Capital Utilization: {_percent(item.capital_utilization_pct)}",
                f"CAGR: {_percent(item.cagr_pct)}",
            )
        )
    lines.extend(
        ("", "Unavailable metrics are never estimated.", "Production Influence: false")
    )
    return tuple(lines)


def render_journal(rows: tuple[PositionJournalRow, ...]) -> tuple[str, ...]:
    lines = ["Immutable Recommendation Journal", f"Records: {len(rows)}"]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            (
                "",
                f"{index}. {row.symbol} — {row.status.value}",
                f"   Policy: {row.policy_version.value}",
                f"   Generated: {row.generated_at.isoformat()}",
                f"   Entry: {_money(row.entry_price)}",
                f"   Exit: {_money(row.exit_price)}",
                f"   Return: {_percent(row.return_pct)}",
                f"   Exit Reason: {row.exit_reason or 'not exited'}",
                f"   Evidence Hash: {row.supporting_evidence_hash}",
            )
        )
    lines.extend(
        ("", "Journal records are append-only.", "Production Influence: false")
    )
    return tuple(lines)


def render_approval_policy(report: ApprovalOptimizationReport) -> tuple[str, ...]:
    lines = [
        "Institutional Approval Policy Audit",
        f"Current Policy: {report.policy_version.value}",
        "Candidates / Resolved Outcomes: "
        f"{report.source_population} / {report.outcome_population}",
        "",
        "Gate Survival:",
    ]
    for gate in report.gates:
        lines.append(
            f"- {gate.label}: {gate.candidates_entering} in, "
            f"{gate.candidates_passing} pass, {gate.candidates_rejected} reject, "
            f"{gate.profitable_rejected_candidates} profitable rejects"
        )
        lines.append(
            "  Avg accepted/rejected return: "
            f"{_percent(gate.average_return_accepted_pct)} / "
            f"{_percent(gate.average_return_rejected_pct)} | "
            f"Precision: {_percent(gate.precision_contribution_pct)} | "
            f"Recall: {_percent(gate.recall_contribution_pct)}"
        )
        lines.append(
            "  Profit factor / expectancy contribution: "
            f"{_number(gate.profit_factor_contribution)} / "
            f"{_percent(gate.expectancy_contribution_pct)} | "
            f"Drawdown reduction: {_percent(gate.drawdown_reduction_pct)} | "
            f"Utilization impact: {_percent(gate.capital_utilization_impact_pct)} | "
            f"Redundant: {str(gate.redundant_on_observed_population).lower()}"
        )
    audit = report.stop_distance_audit
    lines.extend(
        (
            "",
            "Stop Distance Audit:",
            f"- Classification: {audit.classification.value}",
            "- At Gate / Passed: "
            f"{audit.candidates_at_gate} / {audit.candidates_passing}",
            "- Observed Range: "
            f"{_range(audit.minimum_distance_pct, audit.maximum_distance_pct)}",
            "- Current / Validated Candidate Threshold: "
            f"{_percent(audit.current_threshold_pct)} / "
            f"{_percent(audit.recommended_threshold_pct)}",
            "",
            f"Recommendation: {report.recommendation.value}",
            f"Reason: {report.recommendation_reason}",
            "Production Influence: false",
        )
    )
    return tuple(lines)


def render_optimizer(report: ApprovalOptimizationReport) -> tuple[str, ...]:
    lines = [
        "Approval Policy Optimizer",
        f"Counterfactuals Evaluated: {len(report.candidates)}",
    ]
    for candidate in report.candidates:
        lines.extend(
            (
                "",
                f"{candidate.policy_version.value} — {candidate.operation.value}",
                f"  Stage: {candidate.stage.value}",
                f"  Change: {candidate.description}",
            )
        )
        for scorecard in candidate.scorecards:
            lines.append("  " + _scorecard(scorecard))
    lines.extend(
        (
            "",
            f"Recommendation: {report.recommendation.value}",
            f"Reason: {report.recommendation_reason}",
            "Production Influence: false",
        )
    )
    return tuple(lines)


def render_counterfactuals(report: ApprovalOptimizationReport) -> tuple[str, ...]:
    lines = ["Approval Policy Counterfactuals"]
    for candidate in report.candidates:
        parameter_text = ", ".join(
            f"{key}={value}" for key, value in candidate.parameters.items()
        )
        lines.append(
            f"- {candidate.policy_version.value}: {candidate.operation.value} | "
            f"{candidate.stage.value} | {parameter_text or 'no parameter change'}"
        )
    lines.extend(
        (
            "",
            f"Recommendation: {report.recommendation.value}",
            "All candidates are offline or forward-validation-only.",
            "Production Influence: false",
        )
    )
    return tuple(lines)


def render_readiness(report: DeploymentReadinessReport) -> tuple[str, ...]:
    candidate = report.candidate_policy.value if report.candidate_policy else "none"
    lines = [
        "Deployment Readiness",
        f"Classification: {report.readiness.value}",
        f"Candidate Policy: {candidate}",
        f"Reason: {report.reason}",
        "",
        "Missing Evidence:",
    ]
    lines.extend(f"- {item}" for item in report.missing_evidence)
    if not report.missing_evidence:
        lines.append("- None")
    lines.extend(("", "Production Influence: false"))
    return tuple(lines)


def _scorecard(item: PolicyScorecard) -> str:
    return (
        f"{item.split.value}: n={item.sample_count}, approved={item.approved_count}, "
        f"precision={_percent(item.precision_pct)}, "
        f"expectancy={_percent(item.expectancy_pct)}, "
        f"drawdown={_percent(item.maximum_drawdown_proxy_pct)}, "
        f"pass={str(item.passed_baseline).lower()}"
    )


def _money(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"₹{value:,.2f}"


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}%"


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}"


def _zone(low: Decimal | None, high: Decimal | None) -> str:
    if low is None and high is None:
        return "unavailable"
    if low is None:
        return _money(high)
    if high is None:
        return _money(low)
    return f"{_money(low)} to {_money(high)}"


def _range(low: Decimal | None, high: Decimal | None) -> str:
    if low is None or high is None:
        return "unavailable"
    return f"{low:.2f}% to {high:.2f}%"


def _targets(snapshot: RecommendationSnapshot) -> str:
    available = tuple(
        value
        for value in (snapshot.target_1, snapshot.target_2, snapshot.target_3)
        if value is not None
    )
    return ", ".join(_money(value) for value in available) or "unavailable"


__all__ = [
    "render_approval_policy",
    "render_counterfactuals",
    "render_journal",
    "render_optimizer",
    "render_performance",
    "render_portfolios",
    "render_readiness",
    "render_snapshot",
    "render_start",
    "render_update",
]
