from __future__ import annotations

import hashlib

from alpha.gate_dependency_audit.models import GateDefinition, GateGroup

CORE_GATE_SEQUENCE = (
    GateDefinition("VERDICT_QUALITY", "Verdict quality", GateGroup.VERDICT, 1),
    GateDefinition("LATE_ENTRY", "Late-entry exclusion", GateGroup.TIMING, 2),
    GateDefinition(
        "ENTRY_ACTIONABILITY",
        "Entry actionability",
        GateGroup.TIMING,
        3,
    ),
    GateDefinition(
        "ADJUSTED_CONFIDENCE",
        "Adjusted confidence",
        GateGroup.EVIDENCE,
        4,
    ),
    GateDefinition(
        "FINAL_EVIDENCE_SCORE",
        "Final evidence score",
        GateGroup.SETUP_TREND,
        5,
    ),
    GateDefinition(
        "ADAPTIVE_EVIDENCE",
        "Adaptive evidence strength",
        GateGroup.EVIDENCE,
        6,
    ),
    GateDefinition(
        "HISTORICAL_SAMPLE",
        "Matched historical samples",
        GateGroup.EVIDENCE,
        7,
    ),
    GateDefinition(
        "HISTORICAL_EDGE",
        "Historical expectancy and posterior",
        GateGroup.EVIDENCE,
        8,
    ),
    GateDefinition(
        "REWARD_RISK_AVAILABILITY",
        "Reward/risk availability",
        GateGroup.TRADE_PLAN,
        9,
    ),
    GateDefinition(
        "TRADE_PLAN_COMPLETENESS",
        "Trade-plan completeness",
        GateGroup.TRADE_PLAN,
        10,
    ),
    GateDefinition(
        "REWARD_RISK_MINIMUM",
        "Institutional reward/risk minimum",
        GateGroup.TRADE_PLAN,
        11,
        conditional_on="TRADE_PLAN_COMPLETENESS",
    ),
    GateDefinition(
        "STOP_DISTANCE",
        "Maximum stop distance",
        GateGroup.RISK,
        12,
    ),
    GateDefinition(
        "DATA_COMPLETENESS",
        "Data completeness",
        GateGroup.DATA_QUALITY,
        13,
    ),
    GateDefinition("CAPACITY", "Liquidity and capacity", GateGroup.CAPACITY, 14),
    GateDefinition("LIVE_FEED", "Live-feed health", GateGroup.LIVE_FEED, 15),
    GateDefinition("SETUP_QUALITY", "Setup quality", GateGroup.SETUP_TREND, 16),
    GateDefinition(
        "SETUP_SCORECARD",
        "Setup scorecard",
        GateGroup.SETUP_TREND,
        17,
    ),
    GateDefinition("ENTRY_QUALITY", "Entry quality", GateGroup.TIMING, 18),
)

AGGREGATE_GATES = (
    GateDefinition(
        "INSTITUTIONAL_DECISION",
        "Institutional decision",
        GateGroup.INSTITUTIONAL,
        19,
    ),
    GateDefinition(
        "PORTFOLIO_ALLOCATION",
        "Portfolio allocation",
        GateGroup.PORTFOLIO,
        20,
    ),
)

FULL_GATE_SEQUENCE = CORE_GATE_SEQUENCE + AGGREGATE_GATES


def criterion_for_failure(code: str, explanation: str) -> str:
    normalized = explanation.strip().lower()
    direct = {
        "WEAK_VERDICT": "VERDICT_QUALITY",
        "LATE_ENTRY": "LATE_ENTRY",
        "WEAK_CONFIDENCE": "ADJUSTED_CONFIDENCE",
        "POOR_HISTORICAL_EDGE": "HISTORICAL_EDGE",
        "POOR_REWARD_RISK": "REWARD_RISK_MINIMUM",
        "EXCESS_DOWNSIDE_RISK": "STOP_DISTANCE",
        "POOR_DATA_COMPLETENESS": "DATA_COMPLETENESS",
        "INSUFFICIENT_CAPACITY": "CAPACITY",
        "LIVE_FEED_UNHEALTHY": "LIVE_FEED",
    }
    if code in direct:
        return direct[code]
    if code == "PENDING_ENTRY_TRIGGER":
        if normalized.startswith("entry is not actionable"):
            return "ENTRY_ACTIONABILITY"
        if normalized.startswith("entry quality is poor"):
            return "ENTRY_QUALITY"
    if code == "WEAK_SETUP":
        if normalized.startswith("final evidence score"):
            return "FINAL_EVIDENCE_SCORE"
        if normalized.startswith("setup quality"):
            return "SETUP_QUALITY"
        if normalized.startswith("setup scorecard"):
            return "SETUP_SCORECARD"
    if code == "INSUFFICIENT_EVIDENCE":
        if normalized.startswith("adaptive evidence"):
            return "ADAPTIVE_EVIDENCE"
        if "completed historical samples" in normalized:
            return "HISTORICAL_SAMPLE"
    if code == "MISSING_TRADE_PLAN":
        if normalized.startswith("reward/risk is unavailable"):
            return "REWARD_RISK_AVAILABILITY"
        if normalized.startswith("fresh deployment requires entry"):
            return "TRADE_PLAN_COMPLETENESS"
    raise ValueError(f"unmapped frozen gate failure: {code}: {explanation}")


def gate_sequence_hash() -> str:
    payload = "\n".join(
        f"{item.sequence}|{item.gate_id}|{item.group.value}|{item.conditional_on or ''}"
        for item in FULL_GATE_SEQUENCE
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "AGGREGATE_GATES",
    "CORE_GATE_SEQUENCE",
    "FULL_GATE_SEQUENCE",
    "criterion_for_failure",
    "gate_sequence_hash",
]
