from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from alpha.decision_intelligence.models import (
    InstitutionalDecisionReport,
    OpportunityDecision,
    RejectionReasonCode,
    StressReasonCode,
)


class DisqualificationCategory(StrEnum):
    BAD_ENTRY = "bad entry"
    POOR_REWARD_RISK = "poor reward/risk"
    WEAK_VOLUME = "weak volume"
    BEARISH_CONTRADICTION = "bearish contradiction"
    INSUFFICIENT_FIVE_YEAR_DATA = "insufficient 5-year data"
    LATE_SETUP = "late setup"
    NO_HISTORICAL_EDGE = "no historical edge"
    POOR_HISTORICAL_EDGE = "poor historical edge"
    WEAK_CONFIDENCE = "weak confidence"
    DATA_OR_CAPACITY = "data/capacity"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CandidateDisqualification:
    symbol: str
    final_verdict: str
    category: DisqualificationCategory
    primary_reason: str
    details: tuple[str, ...]
    improvement: str


@dataclass(frozen=True, slots=True)
class TradeSetupDisqualificationReport:
    candidates_scanned: int
    disqualified: tuple[CandidateDisqualification, ...]
    category_counts: tuple[tuple[DisqualificationCategory, int], ...]


class TradeSetupDisqualificationReporter:
    def build(
        self,
        report: InstitutionalDecisionReport,
    ) -> TradeSetupDisqualificationReport:
        disqualified = tuple(
            _disqualification(decision)
            for decision in report.decisions
            if not decision.accepted
        )
        counts = Counter(item.category for item in disqualified)
        return TradeSetupDisqualificationReport(
            candidates_scanned=report.candidates_scanned,
            disqualified=disqualified,
            category_counts=tuple(counts.most_common()),
        )


def render_trade_setup_disqualification_report(
    report: TradeSetupDisqualificationReport,
) -> tuple[str, ...]:
    lines = [
        "Trade Setup Disqualification Report",
        f"Candidates Scanned: {report.candidates_scanned}",
        f"Failed Setups: {len(report.disqualified)}",
        "",
        "Failure Mix:",
    ]
    if report.category_counts:
        lines.extend(
            f"- {category.value}: {count}" for category, count in report.category_counts
        )
    else:
        lines.append("- none")
    lines.extend(("", "Candidate Failures:"))
    if not report.disqualified:
        lines.append("- none")
        return tuple(lines)
    for index, item in enumerate(report.disqualified, start=1):
        lines.append(f"{index}. {item.symbol} — {item.category.value}")
        lines.append(f"   Verdict: {item.final_verdict}")
        lines.append(f"   Primary Reason: {item.primary_reason}")
        lines.append(f"   What Would Fix It: {item.improvement}")
        if item.details:
            lines.append("   Evidence:")
            lines.extend(f"   - {detail}" for detail in item.details)
    return tuple(lines)


def _disqualification(decision: OpportunityDecision) -> CandidateDisqualification:
    category = _category(decision)
    reasons = tuple(
        f"{reason.code.value}: {reason.explanation}"
        for reason in decision.rejection_reasons
    )
    stress = tuple(
        f"{result.reason_code.value}: {result.explanation}"
        for result in decision.stress_tests
        if not result.passed
    )
    bearish = tuple(decision.candidate.bearish_indicator_reasons)
    details = (*reasons, *stress, *bearish)
    return CandidateDisqualification(
        symbol=decision.candidate.symbol,
        final_verdict=decision.candidate.final_verdict,
        category=category,
        primary_reason=_primary_reason(category, details),
        details=details,
        improvement=_improvement(category),
    )


def _category(decision: OpportunityDecision) -> DisqualificationCategory:
    codes = {reason.code for reason in decision.rejection_reasons}
    stress_codes = {
        result.reason_code for result in decision.stress_tests if not result.passed
    }
    candidate = decision.candidate
    if RejectionReasonCode.LATE_ENTRY in codes:
        return DisqualificationCategory.LATE_SETUP
    if RejectionReasonCode.PENDING_ENTRY_TRIGGER in codes:
        return DisqualificationCategory.BAD_ENTRY
    if RejectionReasonCode.POOR_REWARD_RISK in codes:
        return DisqualificationCategory.POOR_REWARD_RISK
    if (
        StressReasonCode.BUY_CONTRADICTED_BY_SELL_INDICATORS in stress_codes
        or candidate.bearish_indicator_count > 0
    ):
        return DisqualificationCategory.BEARISH_CONTRADICTION
    if StressReasonCode.INSUFFICIENT_FIVE_YEAR_HISTORY in stress_codes:
        return DisqualificationCategory.INSUFFICIENT_FIVE_YEAR_DATA
    if RejectionReasonCode.POOR_HISTORICAL_EDGE in codes:
        return DisqualificationCategory.POOR_HISTORICAL_EDGE
    if (
        RejectionReasonCode.INSUFFICIENT_EVIDENCE in codes
        or candidate.evidence_strength in {None, "", "insufficient"}
    ):
        return DisqualificationCategory.NO_HISTORICAL_EDGE
    if RejectionReasonCode.WEAK_CONFIDENCE in codes:
        return DisqualificationCategory.WEAK_CONFIDENCE
    if (
        RejectionReasonCode.POOR_DATA_COMPLETENESS in codes
        or RejectionReasonCode.INSUFFICIENT_CAPACITY in codes
    ):
        return DisqualificationCategory.DATA_OR_CAPACITY
    if candidate.capacity.liquidity_warning:
        return DisqualificationCategory.WEAK_VOLUME
    return DisqualificationCategory.OTHER


def _primary_reason(
    category: DisqualificationCategory,
    details: tuple[str, ...],
) -> str:
    if details:
        return details[0]
    return f"Setup failed the {category.value} check."


def _improvement(category: DisqualificationCategory) -> str:
    improvements = {
        DisqualificationCategory.BAD_ENTRY: (
            "Wait for confirmation or a cleaner entry zone with defined risk."
        ),
        DisqualificationCategory.POOR_REWARD_RISK: (
            "Improve entry, reduce stop distance, or wait for a more realistic target."
        ),
        DisqualificationCategory.WEAK_VOLUME: (
            "Require stronger volume expansion or better traded-value support."
        ),
        DisqualificationCategory.BEARISH_CONTRADICTION: (
            "Do not buy until bearish price-volume evidence is repaired."
        ),
        DisqualificationCategory.INSUFFICIENT_FIVE_YEAR_DATA: (
            "Load at least 1,260 historical bars before trusting the setup."
        ),
        DisqualificationCategory.LATE_SETUP: (
            "Avoid chasing; wait for a fresh base, pullback, or reset."
        ),
        DisqualificationCategory.NO_HISTORICAL_EDGE: (
            "Accumulate more completed replay samples for this setup/regime."
        ),
        DisqualificationCategory.POOR_HISTORICAL_EDGE: (
            "Wait for a setup/regime with positive replay expectancy or stronger "
            "completed forward evidence."
        ),
        DisqualificationCategory.WEAK_CONFIDENCE: (
            "Require stronger aligned evidence before capital is approved."
        ),
        DisqualificationCategory.DATA_OR_CAPACITY: (
            "Improve data completeness, liquidity, or capacity evidence."
        ),
        DisqualificationCategory.OTHER: (
            "Review gate, stress-test, and trade-plan details before reconsidering."
        ),
    }
    return improvements[category]


__all__ = [
    "CandidateDisqualification",
    "DisqualificationCategory",
    "TradeSetupDisqualificationReport",
    "TradeSetupDisqualificationReporter",
    "render_trade_setup_disqualification_report",
]
