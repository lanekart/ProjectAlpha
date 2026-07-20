from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from alpha.decision_intelligence.models import (
    InstitutionalDecisionReport,
    OpportunityDecision,
    RejectionReasonCode,
    StressReasonCode,
)

_MIN_WATCHLIST_FINAL_SCORE = Decimal("85")
_MIN_WATCHLIST_SETUP_SCORE = Decimal("70")
_MIN_REWARD_RISK = Decimal("2")
_MAX_STOP_DISTANCE_PERCENT = Decimal("10")


class OpportunityPipelineAction(StrEnum):
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    REJECT = "REJECT"


class WatchlistReasonCode(StrEnum):
    UNFAVOURABLE_RISK_REWARD = "UNFAVOURABLE_RISK_REWARD"
    STOP_DISTANCE_TOO_WIDE = "STOP_DISTANCE_TOO_WIDE"
    ENTRY_EXTENDED = "ENTRY_EXTENDED"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    WAIT_FOR_CONSOLIDATION = "WAIT_FOR_CONSOLIDATION"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class PromotionTrigger:
    description: str

    def __post_init__(self) -> None:
        description = self.description.strip()
        if not description:
            raise ValueError("promotion trigger description cannot be empty")
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class OpportunityPipelineDecision:
    decision: OpportunityDecision
    action: OpportunityPipelineAction
    watchlist_reasons: tuple[WatchlistReasonCode, ...] = ()
    promotion_triggers: tuple[PromotionTrigger, ...] = ()
    explanation: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", OpportunityPipelineAction(self.action))
        object.__setattr__(
            self,
            "watchlist_reasons",
            tuple(WatchlistReasonCode(reason) for reason in self.watchlist_reasons),
        )
        object.__setattr__(self, "promotion_triggers", tuple(self.promotion_triggers))
        explanation = self.explanation.strip()
        if not explanation:
            raise ValueError("opportunity pipeline explanation cannot be empty")
        object.__setattr__(self, "explanation", explanation)
        if self.action is OpportunityPipelineAction.WATCHLIST:
            if not self.watchlist_reasons:
                raise ValueError("watchlist decisions require at least one reason")
            if not self.promotion_triggers:
                raise ValueError(
                    "watchlist decisions require at least one promotion trigger"
                )

    @property
    def symbol(self) -> str:
        return self.decision.candidate.symbol


@dataclass(frozen=True, slots=True)
class OpportunityPipelineReport:
    decisions: tuple[OpportunityPipelineDecision, ...]
    buy_opportunities: tuple[OpportunityPipelineDecision, ...]
    watchlist_opportunities: tuple[OpportunityPipelineDecision, ...]
    rejected_opportunities: tuple[OpportunityPipelineDecision, ...]


class OpportunityPipelineEngine:
    """Preserve bullish opportunities that fail only on execution readiness.

    This layer does not weaken or bypass institutional deployment gates. A WATCHLIST
    action remains non-executable and exists only to prevent high-quality bullish
    candidates from being discarded as generic rejections.
    """

    def build(
        self,
        report: InstitutionalDecisionReport,
    ) -> OpportunityPipelineReport:
        classified = tuple(self.classify(decision) for decision in report.decisions)
        buy = tuple(
            item
            for item in classified
            if item.action is OpportunityPipelineAction.BUY
        )
        watchlist = tuple(
            sorted(
                (
                    item
                    for item in classified
                    if item.action is OpportunityPipelineAction.WATCHLIST
                ),
                key=lambda item: (
                    -item.decision.score_breakdown.total_score,
                    item.symbol,
                ),
            )
        )
        rejected = tuple(
            item
            for item in classified
            if item.action is OpportunityPipelineAction.REJECT
        )
        return OpportunityPipelineReport(
            decisions=classified,
            buy_opportunities=buy,
            watchlist_opportunities=watchlist,
            rejected_opportunities=rejected,
        )

    def classify(
        self,
        decision: OpportunityDecision,
    ) -> OpportunityPipelineDecision:
        if decision.accepted:
            return OpportunityPipelineDecision(
                decision=decision,
                action=OpportunityPipelineAction.BUY,
                explanation="All institutional deployment gates passed.",
            )
        if not self._watchlist_eligible(decision):
            return OpportunityPipelineDecision(
                decision=decision,
                action=OpportunityPipelineAction.REJECT,
                explanation=(
                    "Candidate failed a hard evidence, direction, data, liquidity, "
                    "historical-edge, or risk-control requirement."
                ),
            )
        reasons = self._watchlist_reasons(decision)
        triggers = self._promotion_triggers(decision, reasons)
        return OpportunityPipelineDecision(
            decision=decision,
            action=OpportunityPipelineAction.WATCHLIST,
            watchlist_reasons=reasons,
            promotion_triggers=triggers,
            explanation=(
                "Bullish opportunity quality remains intact, but fresh capital is "
                "not deployable because execution readiness or reward/risk is "
                "currently unfavourable."
            ),
        )

    def _watchlist_eligible(self, decision: OpportunityDecision) -> bool:
        candidate = decision.candidate
        scorecard = candidate.setup_scorecard
        if candidate.final_verdict not in {"BUY", "STRONG_BUY"}:
            return False
        if candidate.final_score < _MIN_WATCHLIST_FINAL_SCORE:
            return False
        if scorecard is None or scorecard.total_score < _MIN_WATCHLIST_SETUP_SCORE:
            return False
        if candidate.data_completeness not in {"COMPLETE", "GOOD"}:
            return False
        if not candidate.capacity.data_sufficient:
            return False
        if candidate.capacity.capacity_score < Decimal("35"):
            return False
        if candidate.live_feed_healthy is False:
            return False
        if candidate.bearish_indicator_count > 0:
            return False
        if candidate.evidence_strength == "insufficient":
            return False
        if candidate.expectancy is not None and candidate.expectancy < Decimal("0"):
            return False

        allowed_gate_reasons = {
            RejectionReasonCode.POOR_REWARD_RISK,
            RejectionReasonCode.EXCESS_DOWNSIDE_RISK,
            RejectionReasonCode.PENDING_ENTRY_TRIGGER,
            RejectionReasonCode.LATE_ENTRY,
        }
        gate_codes = {reason.code for reason in decision.rejection_reasons}
        if not gate_codes or not gate_codes.issubset(allowed_gate_reasons):
            return False

        hard_stress_codes = {
            StressReasonCode.BAD_MARKET_REGIME,
            StressReasonCode.STALE_OR_INCOMPLETE_DATA,
            StressReasonCode.LOW_CAPACITY,
            StressReasonCode.BUY_CONTRADICTED_BY_SELL_INDICATORS,
            StressReasonCode.INSUFFICIENT_FIVE_YEAR_HISTORY,
            StressReasonCode.RECENT_FAILED_SIMILAR_SETUP,
        }
        return not any(
            not result.passed and result.reason_code in hard_stress_codes
            for result in decision.stress_tests
        )

    def _watchlist_reasons(
        self,
        decision: OpportunityDecision,
    ) -> tuple[WatchlistReasonCode, ...]:
        candidate = decision.candidate
        gate_codes = {reason.code for reason in decision.rejection_reasons}
        reasons: list[WatchlistReasonCode] = []
        if RejectionReasonCode.POOR_REWARD_RISK in gate_codes:
            reasons.append(WatchlistReasonCode.UNFAVOURABLE_RISK_REWARD)
        if RejectionReasonCode.EXCESS_DOWNSIDE_RISK in gate_codes:
            reasons.extend(
                (
                    WatchlistReasonCode.STOP_DISTANCE_TOO_WIDE,
                    WatchlistReasonCode.ENTRY_EXTENDED,
                )
            )
        if RejectionReasonCode.LATE_ENTRY in gate_codes:
            reasons.extend(
                (
                    WatchlistReasonCode.ENTRY_EXTENDED,
                    WatchlistReasonCode.WAIT_FOR_PULLBACK,
                    WatchlistReasonCode.WAIT_FOR_CONSOLIDATION,
                )
            )
        if RejectionReasonCode.PENDING_ENTRY_TRIGGER in gate_codes:
            reasons.append(WatchlistReasonCode.WAIT_FOR_CONFIRMATION)
        if (
            candidate.setup_stage == "LATE"
            and WatchlistReasonCode.ENTRY_EXTENDED not in reasons
        ):
            reasons.append(WatchlistReasonCode.ENTRY_EXTENDED)
        return tuple(dict.fromkeys(reasons))

    def _promotion_triggers(
        self,
        decision: OpportunityDecision,
        reasons: tuple[WatchlistReasonCode, ...],
    ) -> tuple[PromotionTrigger, ...]:
        candidate = decision.candidate
        triggers: list[PromotionTrigger] = []
        if WatchlistReasonCode.UNFAVOURABLE_RISK_REWARD in reasons:
            triggers.append(
                PromotionTrigger(
                    f"Reward/risk improves to at least {_MIN_REWARD_RISK}R."
                )
            )
        if WatchlistReasonCode.STOP_DISTANCE_TOO_WIDE in reasons:
            triggers.append(
                PromotionTrigger(
                    "A structure-based entry forms with stop distance at or below "
                    f"{_MAX_STOP_DISTANCE_PERCENT}%."
                )
            )
        if WatchlistReasonCode.WAIT_FOR_PULLBACK in reasons:
            triggers.append(
                PromotionTrigger(
                    "Price completes a constructive pullback while the bullish "
                    "trend remains intact."
                )
            )
        if WatchlistReasonCode.WAIT_FOR_CONSOLIDATION in reasons:
            triggers.append(
                PromotionTrigger(
                    "Price forms a tight consolidation that restores favourable "
                    "execution asymmetry."
                )
            )
        if WatchlistReasonCode.WAIT_FOR_CONFIRMATION in reasons:
            trigger = candidate.trigger_status.replace("_", " ").lower()
            triggers.append(
                PromotionTrigger(
                    f"Entry trigger becomes confirmed; current status is {trigger}."
                )
            )
        return tuple(dict.fromkeys(triggers))


def render_opportunity_pipeline(
    report: OpportunityPipelineReport,
) -> tuple[str, ...]:
    lines = [
        "Opportunity Pipeline",
        f"Buy Ready: {len(report.buy_opportunities)}",
        f"Watchlist: {len(report.watchlist_opportunities)}",
        f"Rejected: {len(report.rejected_opportunities)}",
        "",
        "Watchlist Opportunities:",
    ]
    if not report.watchlist_opportunities:
        lines.append("- none")
    for item in report.watchlist_opportunities:
        candidate = item.decision.candidate
        lines.extend(
            (
                f"- {item.symbol}: WATCHLIST (non-executable)",
                f"  Directional Verdict: {candidate.final_verdict}",
                "  Execution Readiness: NOT READY",
                "  Opportunity Score: "
                f"{item.decision.score_breakdown.total_score}",
                "  Remark: Strong opportunity remains visible, but current "
                "risk/reward or entry timing is unfavourable.",
                "  Reasons: "
                + ", ".join(reason.value for reason in item.watchlist_reasons),
                "  Promotion Triggers:",
            )
        )
        lines.extend(
            f"  - {trigger.description}" for trigger in item.promotion_triggers
        )
    return tuple(lines)
