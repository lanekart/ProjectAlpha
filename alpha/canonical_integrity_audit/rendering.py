from __future__ import annotations

from collections import Counter

from alpha.canonical_integrity_audit.models import CanonicalIntegrityAuditReport


def render_runtime_summary(report: CanonicalIntegrityAuditReport) -> str:
    replay = report.runtime_replay
    lines = [
        "Canonical Runtime Integrity Audit",
        f"Policy: {report.policy.policy_id}",
        f"Failure Days: {replay.before_failure_days} -> {replay.after_failure_days}",
        (
            "Affected Candidates: "
            f"{replay.before_affected_candidates} -> {replay.after_affected_candidates}"
        ),
        f"Root-Cause Groups: {len(report.runtime_groups)}",
    ]
    for item in report.runtime_groups[:10]:
        lines.append(
            f"- {item.category.value} / {item.pipeline_stage}: "
            f"{item.failure_days} days, {item.affected_candidates} candidates"
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_executive_report(report: CanonicalIntegrityAuditReport) -> str:
    summary = report.summary
    replay = report.runtime_replay
    gates = Counter(
        item.primary_blocker or "NONE"
        for item in report.coverage
        if item.primary_blocker is not None
    )
    divergence = (
        "\n".join(
            f"| {item.divergence_stage} | {item.count:,} | {item.share * 100:.2f}% |"
            for item in report.divergences
        )
        or "| Not measured | 0 | unavailable |"
    )
    root_causes = (
        "\n".join(
            f"| {item.category.value} / {item.pipeline_stage} | "
            f"{item.failure_days:,} | "
            f"{item.affected_candidates:,} |"
            for item in report.runtime_groups
        )
        or "| None | 0 | 0 |"
    )
    blockers = (
        "\n".join(
            f"- {label}: {count:,}"
            for label, count in sorted(
                gates.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        )
        or "- None"
    )
    secondaries = (
        ", ".join(item.value for item in summary.secondary_bottlenecks) or "None"
    )
    parity_exact = (
        "unavailable"
        if summary.exact_parity_rate is None
        else f"{summary.exact_parity_rate * 100:.2f}%"
    )
    parity_semantic = (
        "unavailable"
        if summary.semantic_parity_rate is None
        else f"{summary.semantic_parity_rate * 100:.2f}%"
    )
    affected_line = (
        f"| Affected candidates | {replay.before_affected_candidates:,} | "
        f"{replay.after_affected_candidates:,} |"
    )
    scored_line = (
        f"| Scored candidates | {replay.before_scored_candidates:,} | "
        f"{replay.after_scored_candidates:,} |"
    )
    approval_line = (
        f"| BUY / STRONG_BUY candidates | {replay.before_approval_candidates:,} | "
        f"{replay.after_approval_candidates:,} |"
    )
    institutional_line = (
        f"| Institutional approvals | "
        f"{replay.before_institutional_approvals:,} | "
        f"{replay.after_institutional_approvals:,} |"
    )
    parity_caveat = (
        "TradingView remains a secondary validator. No parity rate is claimed "
        "without imported trade-level CSV evidence."
    )
    return f"""# Canonical Runtime Integrity, TradingView Parity & Opportunity Audit

**Policy:** {report.policy.policy_id}  
**Dataset:** {report.policy.dataset_version} / PROVISIONAL  
**Production influence:** false

## Executive Answer

Primary economic bottleneck: **{summary.primary_bottleneck.value}**.  
Secondary bottlenecks: **{secondaries}**.

## Runtime Integrity

| Measure | Before | After |
|---|---:|---:|
| Failure days | {replay.before_failure_days:,} | {replay.after_failure_days:,} |
{affected_line}
{scored_line}
{approval_line}
{institutional_line}

Repair scope: `{replay.repair_scope}`. {replay.repair}

### Root Causes

| Cause | Days | Candidate observations |
|---|---:|---:|
{root_causes}

## TradingView Parity

- Imported trade-level Pine trades: {summary.pine_trades_imported:,}
- Exact parity rate: {parity_exact}
- Exact or semantic parity rate: {parity_semantic}
- Largest divergence stage: {summary.largest_divergence_stage}

| Divergence stage | Count | Share |
|---|---:|---:|
{divergence}

{parity_caveat}

## Major Opportunity Coverage

- Major opportunities: {summary.major_opportunities:,}
- Captured: {summary.captured:,}
- Partially captured: {summary.partially_captured:,}
- Rejected: {summary.rejected:,}
- Missed: {summary.missed:,}
- Runtime blocked: {summary.runtime_blocked:,}
- Data blocked: {summary.data_blocked:,}
- Highest-value missed opportunity: {summary.highest_value_missed_opportunity}

Top blockers:
{blockers}

## Guardrails

- `PRODUCTION_INFLUENCE=false`
- `NO_POLICY_RELAXATION=true`
- `NO_WEIGHT_CHANGES=true`
- `NO_THRESHOLD_CHANGES=true`
- `NO_STRATEGY_CHANGES=true`
- `NO_APPROVAL_CHANGES=true`
- `DIAGNOSTIC_REPAIRS_ONLY=true`
- `TRADINGVIEW_IS_SECONDARY_VALIDATOR=true`
- `LEGACY_DATA_IS_PROVISIONAL=true`
"""


__all__ = ["render_executive_report", "render_runtime_summary"]
