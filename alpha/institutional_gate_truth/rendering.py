from __future__ import annotations

from decimal import Decimal

from alpha.institutional_gate_truth.models import (
    InstitutionalGateTruthReport,
    ReasonStatistic,
)


def render_executive_report(report: InstitutionalGateTruthReport) -> str:
    effect = report.effectiveness
    counterfactual = report.counterfactual_statistics
    best = _best_reason(report.reason_statistics)
    worst = _worst_reason(report.reason_statistics)
    component = (
        report.component_attribution[0] if report.component_attribution else None
    )
    lines = [
        "# Institutional Gate Truth Audit",
        "",
        f"Baseline: {report.manifest.baseline_id}",
        f"Audit: {report.manifest.audit_version}",
        "Classification: DIAGNOSTIC / RESEARCH",
        "Production Influence: NONE",
        "",
        "## Executive Answer",
        "",
        f"Conclusion: **{effect.conclusion.value}**",
        f"Confidence: **{effect.confidence.value}**",
        effect.confidence_reason,
        "",
        "The audit does not relax, tune, reorder, or otherwise modify any "
        "institutional gate. It measures the original frozen decisions against "
        "strictly later market data.",
        "",
        "## Rejection Truth",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Rejected BUY / STRONG BUY population | {effect.rejected_population:,} |",
        f"| Correct rejections | {effect.correct_rejections:,} |",
        f"| False rejections | {effect.false_rejections:,} |",
        f"| Marginal | {effect.marginal_rejections:,} |",
        f"| Data uncertain | {effect.data_uncertain_rejections:,} |",
        "| Rejection accuracy | "
        f"{_percent(effect.overall_rejection_accuracy_percent)} |",
        "| False rejection rate | "
        f"{_percent(effect.overall_false_rejection_rate_percent)} |",
        f"| Opportunity value lost | INR {_number(effect.opportunity_value_lost)} |",
        "| Capital protection gained | INR "
        f"{_number(effect.capital_protection_gained)} |",
        f"| Average missed return | {_percent(effect.average_missed_return_percent)} |",
        f"| Average avoided loss | {_percent(effect.average_avoided_loss_percent)} |",
        "",
        "## Gate-Off Counterfactual",
        "",
        "Current Alpha executed **0 trades** under the frozen gate. The diagnostic "
        "counterfactual includes every rejected BUY whose frozen entry triggered.",
        "",
        "| Metric | Current Alpha | Gate-Off Counterfactual |",
        "|---|---:|---:|",
        f"| Trades | 0 | {counterfactual.entered_trades:,} |",
        f"| Completed trades | 0 | {counterfactual.completed_trades:,} |",
        f"| Win rate | unavailable | {_percent(counterfactual.win_rate_percent)} |",
        f"| Payoff ratio | unavailable | {_number(counterfactual.payoff_ratio)} |",
        f"| Expectancy | unavailable | {_percent(counterfactual.expectancy_percent)} |",
        f"| CAGR | 0.00% | {_percent(counterfactual.cagr_percent)} |",
        "| Maximum drawdown | 0.00% | "
        f"{_percent(counterfactual.maximum_drawdown_percent)} |",
        f"| Sharpe | unavailable | {_number(counterfactual.sharpe_ratio)} |",
        f"| Sortino | unavailable | {_number(counterfactual.sortino_ratio)} |",
        "",
        counterfactual.methodology,
        "",
        "## Rejection Reasons",
        "",
        "| Scope | Reason | Rejected | Correct | False | Marginal | "
        "Uncertain | Accuracy |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.reason_scope} | {item.rejection_reason} | {item.rejected:,} | "
        f"{item.correct:,} | {item.false:,} | {item.marginal:,} | "
        f"{item.data_uncertain:,} | "
        f"{_percent(item.rejection_accuracy_percent)} |"
        for item in report.reason_statistics
    )
    lines.extend(
        [
            "",
            "## Attribution",
            "",
            (
                "Primary false-rejection component: unavailable."
                if component is None
                else f"Primary false-rejection component: **{component.component}** "
                f"({component.false_rejections:,}, "
                f"{_percent(component.false_rejection_share_percent)} of false "
                "rejections)."
            ),
            (
                "Best rejection reason: unavailable."
                if best is None
                else f"Best rejection reason: **{best.rejection_reason}** at "
                f"{_percent(best.rejection_accuracy_percent)} accuracy "
                f"across {best.evaluable:,} evaluable outcomes."
            ),
            (
                "Worst rejection reason: unavailable."
                if worst is None
                else f"Worst rejection reason: **{worst.rejection_reason}** at "
                f"{_percent(worst.false_rejection_rate_percent)} false-rejection "
                f"rate across {worst.evaluable:,} evaluable outcomes."
            ),
            "",
            "Full recommendation component scores were not persisted by CABR v1.0. "
            "IGTA reports them as UNAVAILABLE_IN_CABR_BASELINE and uses the frozen "
            "gate categories for attribution. No score was reconstructed with "
            "hindsight.",
            "",
            "## Primary Recommendation",
            "",
            effect.primary_recommendation,
            "",
            "## Methodology Guardrails",
            "",
            "- Entry must trigger within the frozen five-session validity window.",
            "- Planned stop, target, holding period, costs, and slippage are "
            "unchanged.",
            "- A same-bar stop and target resolves stop first.",
            "- 20D, 60D, and 120D outcomes are measured independently.",
            "- Incomplete or invalid evidence remains DATA_UNCERTAIN.",
            "- The legacy warehouse is provisional; identity and corporate-action "
            "limitations cap overall confidence.",
            "",
            "PRODUCTION_INFLUENCE=false",
            "NO_GATE_CHANGES=true",
            "NO_WEIGHT_CHANGES=true",
            "NO_THRESHOLD_CHANGES=true",
            "NO_FEATURE_CHANGES=true",
            "",
        ]
    )
    return "\n".join(lines)


def render_audit_summary(report: InstitutionalGateTruthReport) -> str:
    effect = report.effectiveness
    counterfactual = report.counterfactual_statistics
    return "\n".join(
        (
            "Institutional Gate Truth Audit",
            f"Rejected BUY Population: {effect.rejected_population}",
            f"Correct Rejections: {effect.correct_rejections}",
            f"False Rejections: {effect.false_rejections}",
            f"Marginal: {effect.marginal_rejections}",
            f"Data Uncertain: {effect.data_uncertain_rejections}",
            "Rejection Accuracy: "
            f"{_percent(effect.overall_rejection_accuracy_percent)}",
            "False Rejection Rate: "
            f"{_percent(effect.overall_false_rejection_rate_percent)}",
            f"Opportunity Value Lost: INR {_number(effect.opportunity_value_lost)}",
            "Capital Protection Gained: INR "
            f"{_number(effect.capital_protection_gained)}",
            f"Counterfactual CAGR: {_percent(counterfactual.cagr_percent)}",
            "Counterfactual Maximum Drawdown: "
            f"{_percent(counterfactual.maximum_drawdown_percent)}",
            f"Counterfactual Sharpe: {_number(counterfactual.sharpe_ratio)}",
            f"Counterfactual Payoff Ratio: {_number(counterfactual.payoff_ratio)}",
            f"Conclusion: {effect.conclusion.value}",
            f"Primary Recommendation: {effect.primary_recommendation}",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _best_reason(rows: tuple[ReasonStatistic, ...]) -> ReasonStatistic | None:
    eligible = tuple(
        item
        for item in rows
        if item.reason_scope == "PRIMARY"
        and item.rejection_accuracy_percent is not None
    )
    return max(
        eligible,
        key=lambda item: (
            item.rejection_accuracy_percent or Decimal("-1"),
            item.evaluable,
            item.rejection_reason,
        ),
        default=None,
    )


def _worst_reason(rows: tuple[ReasonStatistic, ...]) -> ReasonStatistic | None:
    eligible = tuple(
        item
        for item in rows
        if item.reason_scope == "PRIMARY"
        and item.false_rejection_rate_percent is not None
    )
    return max(
        eligible,
        key=lambda item: (
            item.false_rejection_rate_percent or Decimal("-1"),
            item.evaluable,
            item.rejection_reason,
        ),
        default=None,
    )


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value}%"


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:,.2f}"


__all__ = ["render_audit_summary", "render_executive_report"]
