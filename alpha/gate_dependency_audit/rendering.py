from __future__ import annotations

from decimal import Decimal

from alpha.gate_dependency_audit.models import GateDependencyAuditReport


def render_executive_report(report: GateDependencyAuditReport) -> str:
    bottleneck = report.bottleneck
    order = report.gate_order
    active_marginal = tuple(
        item for item in report.marginal_values if item.candidates_failed_gate > 0
    )
    active_cards = tuple(item for item in report.report_cards if item.failures > 0)
    lines = [
        "# Gate Dependency & Sequential Bottleneck Audit",
        "",
        f"Baseline: {report.manifest.baseline_id}",
        f"Audit: {report.manifest.audit_version}",
        "Classification: DIAGNOSTIC / RESEARCH",
        "Production Influence: NONE",
        "",
        "## Executive Answer",
        "",
        f"Largest sequential bottleneck: **{bottleneck.largest_bottleneck}** "
        f"({bottleneck.largest_bottleneck_candidates:,} first failures).",
        "The gate sequence is conjunctive. Reordering does not change a single "
        "acceptance or false rejection; it changes only first-failure attribution "
        "and potential evaluation cost.",
        "",
        "## Decision Funnel",
        "",
        f"Technical candidates: **{report.technical_candidates:,}**",
        f"BUY / STRONG BUY: **{report.buy_candidates:,}**",
        "",
        "| Gate | Entered | Passed | Rejected | Not Reached | Pass % | Reject % |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.gate_id} | {item.entered_stage:,} | {item.passed:,} | "
        f"{item.rejected:,} | {item.not_reached:,} | "
        f"{_percent(item.pass_percent)} | {_percent(item.reject_percent)} |"
        for item in report.survival
    )
    lines.extend(
        [
            "",
            "## First Failure",
            "",
            "| Scope | Gate | Group | Candidates | Population | Correct | False |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {item.scope} | {item.gate_id} | {item.gate_group} | "
        f"{item.candidates:,} | {_percent(item.population_percent)} | "
        f"{item.correct_rejections:,} | {item.false_rejections:,} |"
        for item in report.first_failures
    )
    lines.extend(
        [
            "",
            "## One-Gate Removal",
            "",
            "| Gate | Failed | Additional Survivors | Correct Released | "
            "False Released | Average Return | Net Protection |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {item.gate_id} | {item.candidates_failed_gate:,} | "
        f"{item.additional_survivors_if_removed:,} | "
        f"{item.correct_rejections_released:,} | "
        f"{item.false_rejections_released:,} | "
        f"{_percent(item.average_return_percent)} | "
        f"INR {_number(item.net_capital_protection)} |"
        for item in active_marginal
    )
    lines.extend(
        [
            "",
            "## Gate Report Cards",
            "",
            "| Gate | Failures | Accuracy | Rejection Precision | Incremental "
            "Survivors | Protection | Opportunity Cost | Grade |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| {item.gate_id} | {item.failures:,} | "
        f"{_percent(item.accuracy_percent)} | "
        f"{_percent(item.rejection_precision_percent)} | "
        f"{item.incremental_survivors:,} | "
        f"INR {_number(item.capital_protection)} | "
        f"INR {_number(item.opportunity_cost)} | {item.grade.value} |"
        for item in active_cards
    )
    lines.extend(
        [
            "",
            "## Dependency Findings",
            "",
            f"- Largest false-rejection contributor: "
            f"**{bottleneck.largest_false_rejection_contributor}** "
            f"({bottleneck.largest_false_rejection_count:,}) in the full "
            "observed failure set.",
            f"- Largest sequential false-rejection blocker: "
            f"**{bottleneck.largest_sequential_false_rejection_contributor}** "
            f"({bottleneck.largest_sequential_false_rejection_count:,}).",
            f"- Largest capital-protection contributor: "
            f"**{bottleneck.largest_capital_protection_contributor}** "
            f"(INR {_number(bottleneck.largest_capital_protection)}).",
            f"- Most redundant pair: **{bottleneck.most_redundant_gate_pair}** "
            f"at {_percent(bottleneck.redundancy_percent)} Jaccard overlap.",
            f"- Strongest supported interaction: "
            f"**{bottleneck.strongest_gate_interaction}**, lift "
            f"{_number(bottleneck.interaction_lift)}.",
            "",
            "## Gate Ordering",
            "",
            f"Active criterion permutations tested: {order.permutations_tested:,}",
            f"Equally efficient orders: {order.equally_efficient_orders:,}",
            f"Current active order: {' > '.join(order.current_order)}",
            f"Most efficient diagnostic order: "
            f"{' > '.join(order.most_efficient_order)}",
            f"Average active gates evaluated: "
            f"{order.current_average_gates_evaluated} current versus "
            f"{order.minimum_average_gates_evaluated} minimum.",
            f"Evaluation reduction: {_percent(order.efficiency_improvement_percent)}",
            "Decision outcomes changed: **No**",
            "",
            order.conclusion,
            "",
            "## Bottleneck Flow",
            "",
            "```mermaid",
            *_flowchart_lines(report),
            "```",
            "",
            "## Recommended Next Research Question",
            "",
            bottleneck.recommended_next_research_question,
            "",
            "## Interpretation Constraints",
            "",
            "- Observed status records every criterion failure accumulated by the "
            "frozen engine.",
            "- Sequential status simulates short-circuit reach in the authoritative "
            "source-code order.",
            "- One-gate removal changes no threshold and releases a candidate only "
            "when every other criterion passed.",
            "- Monetary gate values use an equal-share diagnostic notional from "
            "the frozen baseline capital; they are attribution measures, not a "
            "deployable portfolio forecast.",
            "- Full component scores remain unavailable in CABR; no score was "
            "reconstructed with hindsight.",
            "- Legacy data limitations cap empirical confidence.",
            "",
            "PRODUCTION_INFLUENCE=false",
            "NO_GATE_CHANGES=true",
            "NO_ORDER_CHANGES=true",
            "NO_THRESHOLD_CHANGES=true",
            "",
        ]
    )
    return "\n".join(lines)


def render_audit_summary(report: GateDependencyAuditReport) -> str:
    bottleneck = report.bottleneck
    order = report.gate_order
    return "\n".join(
        (
            "Gate Dependency & Sequential Bottleneck Audit",
            f"BUY / STRONG BUY Population: {report.buy_candidates}",
            f"Largest Bottleneck: {bottleneck.largest_bottleneck} "
            f"({bottleneck.largest_bottleneck_candidates})",
            "Largest False-Rejection Contributor: "
            f"{bottleneck.largest_false_rejection_contributor} "
            f"({bottleneck.largest_false_rejection_count}) observed co-failures",
            "Largest Sequential False-Rejection Blocker: "
            f"{bottleneck.largest_sequential_false_rejection_contributor} "
            f"({bottleneck.largest_sequential_false_rejection_count})",
            "Largest Capital-Protection Contributor: "
            f"{bottleneck.largest_capital_protection_contributor} "
            f"(INR {_number(bottleneck.largest_capital_protection)})",
            f"Most Redundant Pair: {bottleneck.most_redundant_gate_pair}",
            f"Strongest Interaction: {bottleneck.strongest_gate_interaction}",
            f"Ordering Changes Decisions: {order.decision_outcomes_changed}",
            f"Recommended Research: {bottleneck.recommended_next_research_question}",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value}%"


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:,.2f}"


def _flowchart_lines(report: GateDependencyAuditReport) -> tuple[str, ...]:
    lines = [
        "flowchart TD",
        f'    observed["Technical candidates: {report.technical_candidates:,}"]',
        f'    buy["BUY / STRONG BUY: {report.buy_candidates:,}"]',
        "    observed --> buy",
    ]
    prior = "buy"
    for index, item in enumerate(report.survival, start=1):
        if item.entered_stage == 0:
            break
        gate = f"g{index}"
        rejected = f"r{index}"
        lines.extend(
            (
                f'    {gate}["{item.gate_id} pass: {item.passed:,}"]',
                f'    {rejected}["Rejected: {item.rejected:,}"]',
                f"    {prior} --> {gate}",
                f"    {prior} --> {rejected}",
            )
        )
        prior = gate
    lines.append(f'    {prior} --> approved["Institutional approvals: 0"]')
    lines.append('    approved --> portfolio["Portfolio entries: 0"]')
    return tuple(lines)


__all__ = ["render_audit_summary", "render_executive_report"]
