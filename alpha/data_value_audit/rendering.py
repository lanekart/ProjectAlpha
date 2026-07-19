"""Human-readable rendering for the Data Value and ROI Audit."""

# ruff: noqa: E501

from __future__ import annotations

from alpha.data_value_audit.models import (
    BudgetPlan,
    DatasetReportCard,
    DataValueAuditReport,
    ImpactLevel,
    NoveltyClass,
)


def render_audit(report: DataValueAuditReport) -> str:
    highest, lowest = _highest_lowest(report)
    unknown = sum(card.priority_index is None for card in report.cards)
    lines = [
        "Project Alpha - Data Value & ROI Audit",
        f"Version: {report.version}",
        "PRODUCTION_INFLUENCE=false",
        f"Datasets Evaluated: {len(report.cards)}",
        f"Cost-adjusted ROI Estimable: {len(report.cards) - unknown}",
        f"Cost-adjusted ROI Unknown: {unknown}",
        "",
        f"Highest Estimable ROI: {_card_label(highest)}",
        f"Lowest Estimable ROI: {_card_label(lowest)}",
        f"Biggest Infrastructure Unlock: {_card_label(_biggest_infrastructure(report))}",
        f"Biggest Replay Improvement: {_card_label(_biggest_replay(report))}",
        f"Biggest Feature Improvement: {_card_label(_biggest_feature(report))}",
        f"Cheapest High-value Purchase: {_card_label(_cheapest_high_value(report))}",
        "",
        "Methodology",
        report.methodology,
        "Unknown prices are never treated as free or ranked below known prices.",
    ]
    return _finish(lines)


def render_roi(report: DataValueAuditReport) -> str:
    lines = [
        "Project Alpha - Data Value ROI Matrix",
        "PRODUCTION_INFLUENCE=false",
        "Priority index is an ordinal decision-value score, not financial ROI.",
        "",
        "Rank  Dataset                              Value  Priority  ROI      Confidence",
    ]
    for rank, card in enumerate(report.ranked_estimable, start=1):
        lines.append(
            f"{rank:>4}  {card.candidate.name[:35]:<35}  "
            f"{card.gross_value_score:>5}  {str(card.priority_index):>8}  "
            f"{card.roi_class.value:<7}  {card.roi_confidence.value}"
        )
    lines.extend(("", "Standalone ROI Unknown"))
    for card in sorted(
        (item for item in report.cards if item.priority_index is None),
        key=lambda item: (-item.gross_value_score, item.candidate.name),
    ):
        lines.append(
            f"- {card.candidate.name}: value {card.gross_value_score}/100; "
            f"cost={card.cost.status.value}; ROI=UNKNOWN"
        )
    return _finish(lines)


def render_budgets(report: DataValueAuditReport) -> str:
    lines = [
        "Project Alpha - Data Procurement Budgets",
        "PRODUCTION_INFLUENCE=false",
    ]
    for plan in report.budgets:
        lines.extend(
            ("", plan.title, f"Known Annual Spend: INR {plan.known_annual_spend_inr:,}")
        )
        if plan.unallocated_inr is not None:
            lines.append(f"Unallocated: INR {plan.unallocated_inr:,}")
        lines.append(
            "Datasets: " + ", ".join(_dataset_names(report, plan.selected_dataset_ids))
        )
        lines.append(f"Instruction: {plan.procurement_instruction}")
        lines.append(f"Why: {plan.rationale}")
        lines.append("Conditions: " + " ".join(plan.conditions))
    return _finish(lines)


def render_report(report: DataValueAuditReport) -> str:
    highest, lowest = _highest_lowest(report)
    lines = [
        "# Project Alpha Data Value & ROI Audit",
        "",
        "**Classification:** Research / Business Intelligence  ",
        "**PRODUCTION_INFLUENCE=false**",
        "",
        "## Executive Decision",
        "",
        f"- Highest estimable ROI: {_card_label(highest)}.",
        f"- Lowest estimable ROI: {_card_label(lowest)}.",
        f"- Biggest infrastructure unlock: {_card_label(_biggest_infrastructure(report))}.",
        f"- Biggest replay improvement: {_card_label(_biggest_replay(report))}.",
        f"- Biggest feature improvement: {_card_label(_biggest_feature(report))}.",
        f"- Cheapest high-value purchase: {_card_label(_cheapest_high_value(report))}.",
        "",
        "The first procurement priority is authoritative NSE daily history. It is the only published INR 1 lakh candidate that directly replaces Alpha's provisional core across replay, candidate generation, trade planning, attribution and learning. This conclusion remains conditional on written historical-retention and internal non-display research rights.",
        "",
        "## Evidence Boundary",
        "",
        report.methodology,
        "Dataset value scores are transparent ordinal research scores. A missing quote produces `ROI=UNKNOWN`, not a free-cost assumption. Package components are not priced twice. No expected Alpha, precision, CAGR, Sharpe or drawdown improvement is stated.",
        "",
        "## Budget Conclusions",
        "",
    ]
    for plan in report.budgets:
        lines.extend(
            (
                f"### {plan.title}",
                "",
                plan.procurement_instruction,
                "",
                f"Known annual spend: INR {plan.known_annual_spend_inr:,}. "
                f"Selected: {', '.join(_dataset_names(report, plan.selected_dataset_ids))}.",
                "",
            )
        )
    lines.extend(
        (
            "## Confidence",
            "",
            "Confidence is highest for the existence and architectural value of price, identity and corporate-action gaps. It is lower for quote-required feature datasets because Alpha has not yet measured their incremental out-of-sample effect or confirmed commercial scope.",
            "",
            "## Decision Rule",
            "",
            "No dataset enters the canonical warehouse until its source rights are confirmed, a bounded sample passes integrity checks, and its incremental value is tested against the frozen benchmark.",
        )
    )
    return _finish(lines)


def render_procurement_strategy(report: DataValueAuditReport) -> str:
    lines = [
        "# DVRA Procurement Strategy",
        "",
        "**PRODUCTION_INFLUENCE=false**",
        "",
        "## Acquisition Order",
        "",
        "1. Establish official daily price truth and the trading calendar.",
        "2. Establish durable security identity, listing, delisting and symbol lineage.",
        "3. Add corporate actions before certifying returns or long-history features.",
        "4. Add benchmark, membership and sector context for point-in-time attribution.",
        "5. Test delivery and breadth as orthogonal candidate and gate evidence.",
        "6. Test ownership and earnings only after point-in-time sourcing and quote validation.",
        "",
        "## Promotion Contract",
        "",
        "Every purchase requires confirmed rights, a bounded sample, integrity reconciliation, a frozen feature definition and an incremental benchmark experiment. Unlimited budget does not waive these gates.",
        "",
        "## Sensitivity",
        "",
    ]
    for item in report.sensitivity:
        if item.dependent_unlocks_lost:
            lines.append(
                f"- `{item.dataset_id}`: {item.unavailable_effect} "
                f"(ordinal value at risk: {item.value_score_lost}/100; confidence {item.confidence.value})."
            )
    return _finish(lines)


def render_budget_page(report: DataValueAuditReport, plan: BudgetPlan) -> str:
    title = (
        "If I had only INR 1 lakh to spend this year, what should I buy first-and why?"
        if plan.budget_id == "budget_1L"
        else plan.title
    )
    display_title = (
        "If I had only ₹1 lakh to spend this year, what should I buy first—and why?"
        if plan.budget_id == "budget_1L"
        else title
    )
    lines = [
        f"# {display_title}",
        "",
        "**PRODUCTION_INFLUENCE=false**",
        "",
        "## Decision",
        "",
        plan.procurement_instruction,
        "",
        "## Selected Data",
        "",
    ]
    lines.extend(
        f"- {name}" for name in _dataset_names(report, plan.selected_dataset_ids)
    )
    lines.extend(
        (
            "",
            f"Known annual spend: INR {plan.known_annual_spend_inr:,}.",
            "",
            "## Why",
            "",
            plan.rationale,
            "",
            "## Conditions Before Purchase",
            "",
        )
    )
    lines.extend(f"- {condition}" for condition in plan.conditions)
    lines.extend(
        (
            "",
            "## What This Does Not Claim",
            "",
            "This recommendation does not forecast profit, CAGR, Sharpe, precision or opportunity-capture uplift. It ranks documented data dependencies against known cost and leaves unknown contract scope unresolved.",
        )
    )
    return _finish(lines)


def _highest_lowest(
    report: DataValueAuditReport,
) -> tuple[DatasetReportCard | None, DatasetReportCard | None]:
    ranked = report.ranked_estimable
    return (ranked[0], ranked[-1]) if ranked else (None, None)


def _biggest_infrastructure(report: DataValueAuditReport) -> DatasetReportCard:
    return max(
        report.cards,
        key=lambda card: (
            card.infrastructure.score,
            card.gross_value_score,
            card.candidate.name,
        ),
    )


def _biggest_replay(report: DataValueAuditReport) -> DatasetReportCard:
    return max(
        report.cards,
        key=lambda card: (
            sum(item.impact is ImpactLevel.HIGH for item in card.replay.impacts),
            card.gross_value_score,
            card.candidate.name,
        ),
    )


def _biggest_feature(report: DataValueAuditReport) -> DatasetReportCard:
    new_features = tuple(
        card
        for card in report.cards
        if card.candidate.novelty is NoveltyClass.ADDS_NEW_FEATURE
    )
    return max(
        new_features,
        key=lambda card: (
            card.candidate.dataset_id == "delivery_percentage",
            card.decision.score,
            card.information.score,
            card.candidate.name,
        ),
    )


def _cheapest_high_value(report: DataValueAuditReport) -> DatasetReportCard | None:
    candidates = tuple(
        card
        for card in report.cards
        if card.cost.annual_cost_inr is not None
        and card.cost.annual_cost_inr > 0
        and card.gross_value_score >= 70
    )
    return min(
        candidates,
        key=lambda card: (
            int(card.cost.annual_cost_inr or 0),
            -card.gross_value_score,
            card.candidate.name,
        ),
        default=None,
    )


def _dataset_names(
    report: DataValueAuditReport, ids: tuple[str, ...]
) -> tuple[str, ...]:
    names = {card.candidate.dataset_id: card.candidate.name for card in report.cards}
    return tuple(names[dataset_id] for dataset_id in ids)


def _card_label(card: DatasetReportCard | None) -> str:
    if card is None:
        return "UNKNOWN"
    priority = (
        "UNKNOWN" if card.priority_index is None else f"{card.priority_index}/100"
    )
    return f"{card.candidate.name} (priority {priority}, ROI {card.roi_class.value})"


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "render_audit",
    "render_budget_page",
    "render_budgets",
    "render_procurement_strategy",
    "render_report",
    "render_roi",
]
