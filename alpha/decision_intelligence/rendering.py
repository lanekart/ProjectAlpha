from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.candidate_learning import EntryTimingIntelligenceEngine
from alpha.decision_intelligence.models import (
    DecisionAuditReport,
    InstitutionalCandidate,
    InstitutionalDecisionReport,
    OpportunityDecision,
    TradePlanAuditReport,
)


def render_decision_report(
    report: InstitutionalDecisionReport,
    *,
    verbose: bool = False,
) -> tuple[str, ...]:
    lines = [
        "Institutional Decision Report",
        f"Candidates Scanned: {report.candidates_scanned}",
        f"Accepted Opportunities: {len(report.accepted_opportunities)}",
        f"Rejected Opportunities: {len(report.rejected_opportunities)}",
        f"Acceptance Rate: {report.acceptance_rate}",
        f"Average Opportunity Score: {_decimal(report.average_opportunity_score)}",
        f"Evidence Quality Summary: {report.evidence_quality_summary}",
    ]
    if report.no_trade_reason:
        lines.extend(("", report.no_trade_reason))
        lines.append(f"Candidates Rejected: {len(report.rejected_opportunities)}")
        lines.extend(_top_rejection_reason_lines(report))
        lines.append("What Would Improve Eligibility:")
        lines.extend(_eligibility_improvement_lines(report))
    lines.extend(("", "Accepted Opportunities:"))
    if report.accepted_opportunities:
        for index, decision in enumerate(report.accepted_opportunities, start=1):
            lines.extend(_accepted_lines(index, decision))
    else:
        lines.append("- none")
    if report.concentration_warnings:
        lines.extend(("", "Portfolio Concentration Warnings:"))
        lines.extend(f"- {warning}" for warning in report.concentration_warnings)
    if verbose:
        lines.extend(("", "Stress Test Results:"))
        for decision in report.decisions:
            lines.extend(_stress_lines(decision))
        lines.extend(("", "Rejected Candidates:"))
        if report.rejected_opportunities:
            for decision in report.rejected_opportunities:
                lines.extend(_rejected_lines(decision))
        else:
            lines.append("- none")
    return tuple(lines)


def render_default_opportunities(
    report: InstitutionalDecisionReport,
) -> tuple[str, ...]:
    lines = ["Institutional Opportunities"]
    if not report.accepted_opportunities:
        lines.append("No high-quality trade setup today.")
        lines.append("Institutional Deployment Status: NO DEPLOYABLE TRADE")
        lines.append(
            "Alpha is refusing deployment because current candidates do not meet "
            "all institutional approval criteria."
        )
        lines.append(
            "Zero approvals do not prove no profitable setup existed; they mean "
            "no setup cleared today's risk, evidence, and trade-plan gates."
        )
        lines.append(
            "Approval precision is unavailable when no approvals were emitted."
        )
        lines.append(f"Candidates scanned: {report.candidates_scanned}")
        lines.append(f"Candidates rejected: {len(report.rejected_opportunities)}")
        lines.extend(_top_rejection_reason_lines(report))
        lines.append("What would improve eligibility:")
        lines.extend(_eligibility_improvement_lines(report))
        return tuple(lines)
    for index, decision in enumerate(report.accepted_opportunities, start=1):
        lines.extend(_accepted_lines(index, decision))
    return tuple(lines)


def _accepted_lines(index: int, decision: OpportunityDecision) -> list[str]:
    candidate = decision.candidate
    quality = decision.decision_quality
    trade_plan_quality = decision.trade_plan_quality
    plan = (
        trade_plan_quality.final_selected_plan
        if trade_plan_quality is not None
        else None
    )
    trade_plan_grade = (
        trade_plan_quality.trade_plan_grade.value
        if trade_plan_quality is not None
        else "unavailable"
    )
    top_warning = (
        quality.top_risk_warnings[0]
        if quality is not None and quality.top_risk_warnings
        else decision.primary_weakness
    )
    targets = (
        plan.selected_targets
        if plan is not None
        else (candidate.target_1, candidate.target_2, candidate.target_3)
    )
    scorecard = candidate.setup_scorecard
    setup_grade = scorecard.setup_grade.value if scorecard else trade_plan_grade
    entry_status = _entry_status(decision)
    historical_edge = _historical_edge_text(candidate)
    trigger = _trigger_instruction(candidate)
    stop = plan.selected_stop if plan else candidate.stop
    entry = plan.entry if plan else candidate.entry
    reward_risk = plan.reward_risk if plan else candidate.reward_risk_ratio
    timing = EntryTimingIntelligenceEngine().assess_candidate(candidate)
    why = _why_text(
        decision,
        plan.explanation if plan else decision.selection_reason,
    )
    return [
        f"{index}. {candidate.symbol} — {candidate.final_verdict}",
        f"   Verdict: {_verdict_sentence(decision)}",
        f"   Setup Grade: {setup_grade}",
        f"   Entry Status: {entry_status}",
        "   Confidence: "
        f"{candidate.adjusted_confidence} | Historical Edge: {historical_edge}",
        f"   Opportunity Score: {decision.opportunity_score}",
        "   Decision Quality Score: "
        f"{quality.decision_quality_score if quality is not None else 'unavailable'}",
        "   Setup Scorecard: "
        f"{scorecard.summary if scorecard else 'Not yet computed.'}",
        f"   Final Selected Entry: {_decimal(entry)}",
        f"   Optimized Stop: {_decimal(stop)}",
        f"   Optimized Targets: {_targets_text(targets)}",
        f"   Entry Timing: {timing.entry_state.value}",
        f"   Timing Score: {timing.timing_score}/100",
        f"   Current Stop Distance: {_decimal(timing.stop_distance_pct)}%",
        f"   Distance From Support: {_decimal(timing.distance_from_support_pct)}%",
        f"   Price Extension: {_decimal(timing.distance_from_support_atr)} ATR",
        "   Actionability: "
        f"{'TIMING FAVOURABLE' if timing.actionable_now else 'NOT ACTIONABLE NOW'}",
        f"   Timing Reason: {_timing_reason(timing)}",
        "   Trade Plan:",
        f"   - Entry: {_decimal(entry)}",
        f"   - Trigger: {trigger}",
        f"   - Stop Loss: {_decimal(stop)}",
        f"   - Targets: {_targets_text(targets)}",
        f"   - Reward/Risk: {_decimal(reward_risk)}",
        "   Selected Exit Strategy: "
        f"{plan.selected_exit_strategy.value if plan else 'unavailable'}",
        f"   Trade Plan Grade: {trade_plan_grade}",
        "   Capacity: "
        f"{candidate.capacity.capacity_score} — {candidate.capacity.explanation}",
        f"   Why: {why}",
        "   What Would Change My Mind:",
        f"   - Bullish confirmation: {trigger}",
        f"   - Invalidation: exit/avoid if price closes below {_decimal(stop)}.",
        f"   - Risk warning: {top_warning}",
    ]


def _rejected_lines(decision: OpportunityDecision) -> list[str]:
    candidate = decision.candidate
    lines = [
        f"- {candidate.symbol}: Reject",
        "  Gate Decisions: "
        f"{', '.join(reason.code.value for reason in decision.rejection_reasons)}",
        f"  Score Breakdown: {dict(decision.score_breakdown.as_mapping())}",
        f"  Portfolio Penalty: {decision.portfolio_penalty}",
        f"  Capacity Details: {candidate.capacity.explanation}",
    ]
    if candidate.missing_data:
        lines.append(f"  Missing Data: {', '.join(candidate.missing_data)}")
    if candidate.final_verdict in {"AVOID", "SELL", "REJECT"}:
        lines.append(
            "  Re-entry Watch Level: not actionable until price, volume, "
            "setup stage, and risk/reward improve."
        )
    if decision.decision_quality is not None:
        lines.append(
            "  Decision Quality: "
            f"{decision.decision_quality.final_action.value} "
            f"({decision.decision_quality.decision_quality_score})"
        )
        lines.append(
            "  Stop Quality: "
            f"{decision.decision_quality.stop_quality.stop_quality.value} — "
            f"{decision.decision_quality.stop_quality.explanation}"
        )
        lines.append(
            "  Target Quality: "
            f"{decision.decision_quality.target_quality.target_quality.value} — "
            f"{decision.decision_quality.target_quality.explanation}"
        )
        lines.append(
            "  Overconfidence: "
            f"{decision.decision_quality.overconfidence.adjusted_confidence} — "
            f"{decision.decision_quality.overconfidence.explanation}"
        )
    if decision.trade_plan_quality is not None:
        lines.append(
            "  Trade Plan Quality: "
            f"{decision.trade_plan_quality.final_action.value} "
            f"({decision.trade_plan_quality.trade_plan_quality_score})"
        )
        if decision.trade_plan_quality.rejected_stop_candidates:
            lines.append(
                "  Rejected Stop Candidates: "
                + ", ".join(
                    candidate.name
                    for candidate in (
                        decision.trade_plan_quality.rejected_stop_candidates
                    )
                )
            )
        if decision.trade_plan_quality.rejected_target_candidates:
            lines.append(
                "  Rejected Target Candidates: "
                + ", ".join(
                    candidate.name
                    for candidate in (
                        decision.trade_plan_quality.rejected_target_candidates
                    )
                )
            )
        selected_exit = next(
            (
                strategy
                for strategy in decision.trade_plan_quality.exit_strategy_comparison
                if strategy.selected
            ),
            None,
        )
        if selected_exit is not None:
            lines.append(
                "  Selected Exit Strategy: "
                f"{selected_exit.strategy_type.value} — {selected_exit.explanation}"
            )
    lines.extend(
        f"  Reason: {reason.code.value} — {reason.explanation}"
        for reason in decision.rejection_reasons
    )
    return lines


def render_decision_audit(report: DecisionAuditReport) -> tuple[str, ...]:
    lines = [
        "Decision Audit Report",
        f"Candidates Scanned: {report.candidates_scanned}",
        "Institutional Accepted Before Stress Test: "
        f"{report.institutional_accepted_before_stress}",
        f"Final Accepted After Stress Test: {report.final_accepted_after_stress}",
        f"Downgraded: {report.downgraded}",
        f"Rejected By Stress Test: {report.rejected_by_stress}",
        "Average Decision Quality Score: "
        f"{_decimal(report.average_decision_quality_score)}",
        f"Overconfidence Reductions: {report.overconfidence_reductions}",
        "",
        "Top Failure Modes:",
    ]
    if report.top_failure_modes:
        lines.extend(
            f"- {code.value}: {count}" for code, count in report.top_failure_modes
        )
    else:
        lines.append("- none")
    lines.extend(("", "Stop Quality Distribution:"))
    lines.extend(
        f"- {quality}: {count}"
        for quality, count in report.stop_quality_distribution.items()
    )
    lines.extend(("", "Target Quality Distribution:"))
    lines.extend(
        f"- {quality}: {count}"
        for quality, count in report.target_quality_distribution.items()
    )
    if report.no_trade_explanation:
        lines.extend(("", report.no_trade_explanation))
    return tuple(lines)


def render_trade_plan_audit(report: TradePlanAuditReport) -> tuple[str, ...]:
    lines = [
        "Trade Plan Audit",
        f"Accepted Opportunities Reviewed: {report.accepted_opportunities_reviewed}",
        f"Optimized Plans: {report.optimized_plans}",
        f"Rejected Due To Weak Trade Plan: {report.rejected_due_to_weak_trade_plan}",
        "Average Trade Plan Quality Score: "
        f"{_decimal(report.average_trade_plan_quality_score)}",
        "",
        "Stop Quality Distribution:",
    ]
    lines.extend(
        f"- {quality}: {count}"
        for quality, count in report.stop_quality_distribution.items()
    )
    lines.extend(("", "Target Quality Distribution:"))
    lines.extend(
        f"- {quality}: {count}"
        for quality, count in report.target_quality_distribution.items()
    )
    lines.extend(("", "Selected Exit Strategy Distribution:"))
    if report.selected_exit_strategy_distribution:
        lines.extend(
            f"- {strategy}: {count}"
            for strategy, count in report.selected_exit_strategy_distribution.items()
        )
    else:
        lines.append("- none")
    lines.extend(("", "Common Trade Plan Weaknesses:"))
    if report.common_trade_plan_weaknesses:
        lines.extend(
            f"- {weakness}: {count}"
            for weakness, count in report.common_trade_plan_weaknesses
        )
    else:
        lines.append("- none")
    return tuple(lines)


def _stress_lines(decision: OpportunityDecision) -> list[str]:
    if not decision.stress_tests:
        return [f"- {decision.candidate.symbol}: no stress tests run"]
    lines = [f"- {decision.candidate.symbol}:"]
    for result in decision.stress_tests:
        if not result.passed:
            lines.append(
                "  Failed: "
                f"{result.reason_code.value} ({result.severity.value}) — "
                f"{result.explanation}; action={result.suggested_action.value}"
            )
    if len(lines) == 1:
        lines.append("  All stress tests passed.")
    return lines


def _top_rejection_reason_lines(report: InstitutionalDecisionReport) -> list[str]:
    counter = Counter(
        reason.code.value
        for decision in report.rejected_opportunities
        for reason in decision.rejection_reasons
    )
    if not counter:
        return ["Top rejection reasons: none"]
    return [
        "Top rejection reasons:",
        *(f"- {code}: {count}" for code, count in counter.most_common(5)),
    ]


def _eligibility_improvement_lines(report: InstitutionalDecisionReport) -> list[str]:
    codes = {
        reason.code.value
        for decision in report.rejected_opportunities
        for reason in decision.rejection_reasons
    }
    improvements = []
    if "POOR_REWARD_RISK" in codes or "MISSING_TRADE_PLAN" in codes:
        improvements.append("- Cleaner entry/stop/target structure with at least 2R.")
    if "WEAK_CONFIDENCE" in codes or "INSUFFICIENT_EVIDENCE" in codes:
        improvements.append(
            "- Stronger calibrated confidence and more completed samples."
        )
    if "INSUFFICIENT_CAPACITY" in codes:
        improvements.append("- Better liquidity, traded value, or live spread quality.")
    if "POOR_DATA_COMPLETENESS" in codes:
        improvements.append("- More complete price, volume, and trade-plan data.")
    return improvements or ["- A higher-grade opportunity must pass all gates."]


def _decimal(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _targets_text(values: tuple[Decimal | None, ...]) -> str:
    available = tuple(value for value in values if value is not None)
    if not available:
        return "unavailable"
    return ", ".join(str(value) for value in available)


def _entry_status(decision: OpportunityDecision) -> str:
    candidate = decision.candidate
    if candidate.execution_status == "BUY NOW" and candidate.entry_ready:
        return "Entry ready; trigger already confirmed."
    if candidate.setup_stage == "LATE":
        return "Late; no fresh deployment."
    if not candidate.entry_ready:
        return "Waiting for confirmation; no capital approved yet."
    return candidate.execution_status.replace("_", " ").title()


def _historical_edge_text(candidate: InstitutionalCandidate) -> str:
    if candidate.evidence_strength in {None, "", "insufficient"}:
        return "Not yet computed"
    sample = (
        f", sample {candidate.evidence_sample_count}"
        if candidate.evidence_sample_count is not None
        else ""
    )
    return f"{candidate.evidence_strength}{sample}"


def _trigger_instruction(candidate: InstitutionalCandidate) -> str:
    if candidate.entry_ready and candidate.trigger_status == "TRIGGER_CONFIRMED":
        return "Already confirmed; buy only within the approved entry zone."
    if candidate.trigger_status == "WAITING_FOR_VOLUME_CONFIRMATION":
        return "Wait for breakout with above-average volume."
    if candidate.trigger_status == "WAITING_FOR_CROSS_ABOVE":
        return "Wait for price to cross above the trigger level."
    if candidate.trigger_status == "WAITING_FOR_CLOSE_ABOVE":
        return "Wait for a daily close above the trigger level."
    return "Wait; setup is not actionable."


def _verdict_sentence(decision: OpportunityDecision) -> str:
    if decision.accepted:
        return "Actionable trade candidate, subject to portfolio risk limits."
    return "Not deployable."


def _why_text(decision: OpportunityDecision, fallback: str) -> str:
    scorecard = decision.candidate.setup_scorecard
    if scorecard is None:
        return fallback
    return (
        f"{fallback} Setup score is {scorecard.total_score}/100 because "
        f"entry quality is {scorecard.entry_quality}, reward/risk quality is "
        f"{scorecard.reward_risk_quality}, and historical evidence is "
        f"{scorecard.historical_evidence}."
    )


def _timing_reason(timing: object) -> str:
    state = getattr(timing, "entry_state")
    wait_condition = getattr(timing, "wait_condition")
    if getattr(timing, "actionable_now"):
        return (
            "Entry timing is favourable because stop distance and reward/risk "
            "remain acceptable."
        )
    if wait_condition:
        return str(wait_condition)
    return f"Entry timing is {getattr(state, 'value', state)}."


__all__ = [
    "render_decision_audit",
    "render_decision_report",
    "render_default_opportunities",
    "render_trade_plan_audit",
]
