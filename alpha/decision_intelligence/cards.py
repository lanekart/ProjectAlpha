from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from alpha.candidate_learning import LearningLedgerRepository
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
    RawForwardWindowOutcome,
)
from alpha.decision_intelligence.disqualification import (
    DisqualificationCategory,
)
from alpha.decision_intelligence.models import (
    FinalDecisionAction,
    OpportunityDecision,
    RejectionReasonCode,
    StressDecisionAction,
    StressReasonCode,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_PERIODS = ("1d", "3d", "5d", "10d", "20d", "60d")


class RiskCommitteeVerdict(StrEnum):
    APPROVED = "APPROVED"
    WAIT = "WAIT"
    REJECT = "REJECT"
    EXIT = "EXIT"


@dataclass(frozen=True, slots=True)
class SimilarHistoricalCases:
    sample_count: int
    win_rate: Decimal | None
    average_return_pct: Decimal | None
    stop_hit_rate: Decimal | None
    best_holding_period: str | None
    worst_failure_mode: str | None
    evidence_strength: str


@dataclass(frozen=True, slots=True)
class DecisionEvidenceSnapshot:
    symbol: str
    final_verdict: str
    action: RiskCommitteeVerdict
    opportunity_score: Decimal
    adjusted_confidence: str
    setup_stage: str
    entry_ready: bool
    entry: Decimal | None
    stop: Decimal | None
    targets: tuple[Decimal, ...]
    price_volume_state: str
    trend_state: str
    trade_plan_summary: str
    gate_results: tuple[str, ...]
    stress_failures: tuple[str, ...]
    disqualification_category: DisqualificationCategory | None
    similar_cases: SimilarHistoricalCases
    risk_committee_reason: str
    investor_summary: str


class SimilarHistoricalCasesEngine:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def find(self, decision: OpportunityDecision) -> SimilarHistoricalCases:
        records = self.repository.load_raw_records()
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        matched = tuple(
            record
            for record in records
            if _matches_candidate(record=record, decision=decision)
        )
        returns = tuple(
            window.forward_return_pct_from_close
            for record in matched
            if (window := _window(outcomes.get(record.raw_candidate_id), "20d"))
            is not None
            and window.forward_return_pct_from_close is not None
        )
        stop_windows = tuple(
            window
            for record in matched
            if (window := _window(outcomes.get(record.raw_candidate_id), "20d"))
            is not None
        )
        return SimilarHistoricalCases(
            sample_count=len(returns),
            win_rate=_ratio(sum(1 for value in returns if value > 0), len(returns)),
            average_return_pct=_average(returns),
            stop_hit_rate=_ratio(
                sum(1 for window in stop_windows if window.risk_stop_touched),
                len(stop_windows),
            ),
            best_holding_period=_best_holding_period(
                records=matched,
                outcomes=outcomes,
            ),
            worst_failure_mode=_worst_failure_mode(
                records=matched,
                outcomes=outcomes,
            ),
            evidence_strength=_evidence_strength(len(returns)),
        )


class RiskCommitteeGate:
    def review(self, decision: OpportunityDecision) -> tuple[RiskCommitteeVerdict, str]:
        candidate = decision.candidate
        if candidate.final_verdict in {"SELL", "AVOID", "REJECT"}:
            return (
                RiskCommitteeVerdict.EXIT,
                "Avoid or exit; Alpha's final verdict is not long-deployable.",
            )
        if decision.accepted:
            return (
                RiskCommitteeVerdict.APPROVED,
                "Approved because gates, stress tests, and trade plan all passed.",
            )
        if (
            not candidate.entry_ready
            or candidate.trigger_status != "TRIGGER_CONFIRMED"
            or candidate.execution_status != "BUY NOW"
        ):
            return (
                RiskCommitteeVerdict.WAIT,
                "Wait because the setup is not entry-ready or trigger is pending.",
            )
        if (
            decision.decision_quality is not None
            and decision.decision_quality.final_action is FinalDecisionAction.DOWNGRADE
        ):
            return (
                RiskCommitteeVerdict.WAIT,
                "Wait because stress tests downgraded the setup.",
            )
        return (
            RiskCommitteeVerdict.REJECT,
            "Rejected because one or more institutional gates failed.",
        )


class DecisionEvidenceCardBuilder:
    def __init__(
        self,
        *,
        repository: LearningLedgerRepository,
        similar_cases: SimilarHistoricalCasesEngine | None = None,
        risk_committee: RiskCommitteeGate | None = None,
    ) -> None:
        self.similar_cases = similar_cases or SimilarHistoricalCasesEngine(
            repository=repository
        )
        self.risk_committee = risk_committee or RiskCommitteeGate()

    @classmethod
    def from_path(cls) -> DecisionEvidenceCardBuilder:
        return cls(repository=LearningLedgerRepository())

    def build(self, decision: OpportunityDecision) -> DecisionEvidenceSnapshot:
        candidate = decision.candidate
        verdict, reason = self.risk_committee.review(decision)
        similar = self.similar_cases.find(decision)
        disqualification = _disqualification_category(decision)
        targets = tuple(
            target
            for target in (candidate.target_1, candidate.target_2, candidate.target_3)
            if target is not None
        )
        return DecisionEvidenceSnapshot(
            symbol=candidate.symbol,
            final_verdict=candidate.final_verdict,
            action=verdict,
            opportunity_score=decision.opportunity_score,
            adjusted_confidence=candidate.adjusted_confidence,
            setup_stage=candidate.setup_stage,
            entry_ready=candidate.entry_ready,
            entry=candidate.entry,
            stop=candidate.stop,
            targets=targets,
            price_volume_state=_price_volume_state(decision),
            trend_state=_trend_state(decision),
            trade_plan_summary=_trade_plan_summary(decision),
            gate_results=tuple(
                reason.code.value for reason in decision.rejection_reasons
            )
            or ("PASSED",),
            stress_failures=tuple(
                result.reason_code.value
                for result in decision.stress_tests
                if (
                    not result.passed
                    and result.suggested_action is not StressDecisionAction.KEEP
                )
            ),
            disqualification_category=disqualification,
            similar_cases=similar,
            risk_committee_reason=reason,
            investor_summary=_investor_summary(
                symbol=candidate.symbol,
                verdict=verdict,
                reason=reason,
                similar=similar,
            ),
        )

    def build_many(
        self,
        decisions: tuple[OpportunityDecision, ...],
    ) -> tuple[DecisionEvidenceSnapshot, ...]:
        return tuple(self.build(decision) for decision in decisions)


def render_decision_evidence_cards(
    cards: tuple[DecisionEvidenceSnapshot, ...],
    *,
    verbose: bool = False,
) -> tuple[str, ...]:
    lines = ["Unified Decision Cards", f"Cards: {len(cards)}"]
    if not cards:
        lines.append("- none")
        return tuple(lines)
    for index, card in enumerate(cards, start=1):
        lines.append(f"{index}. {card.symbol} — {card.action.value}")
        lines.append(f"   Verdict: {card.final_verdict}")
        lines.append(
            "   Score/Confidence: "
            f"{card.opportunity_score} / {card.adjusted_confidence}"
        )
        lines.append(
            "   Entry/Stop/Targets: "
            f"{_metric(card.entry)} / {_metric(card.stop)} / "
            f"{_targets(card.targets)}"
        )
        lines.append(f"   Risk Committee: {card.risk_committee_reason}")
        lines.append(
            "   Similar Cases: "
            f"sample {card.similar_cases.sample_count}, "
            f"win rate {_metric(card.similar_cases.win_rate)}, "
            f"EV {_metric(card.similar_cases.average_return_pct)}%"
        )
        lines.append(f"   Summary: {card.investor_summary}")
        if verbose:
            lines.append(f"   Price/Volume: {card.price_volume_state}")
            lines.append(f"   Trend: {card.trend_state}")
            lines.append(f"   Trade Plan: {card.trade_plan_summary}")
            lines.append(f"   Gates: {', '.join(card.gate_results)}")
            lines.append(
                "   Stress Failures: " + (", ".join(card.stress_failures) or "none")
            )
            lines.append(
                "   Disqualification: "
                + (
                    card.disqualification_category.value
                    if card.disqualification_category is not None
                    else "none"
                )
            )
            lines.append(
                "   Historical Weakness: "
                f"{card.similar_cases.worst_failure_mode or 'unavailable'}"
            )
    return tuple(lines)


def _matches_candidate(
    *,
    record: RawCandidateRecord,
    decision: OpportunityDecision,
) -> bool:
    candidate = decision.candidate
    same_sector = (record.sector or "UNKNOWN") == candidate.sector
    same_regime = (
        candidate.market_regime is None
        or record.market_regime == candidate.market_regime
    )
    return same_sector and same_regime


def _window(
    outcome: RawCandidateForwardOutcome | None,
    period: str,
) -> RawForwardWindowOutcome | None:
    if outcome is None:
        return None
    return next((window for window in outcome.windows if window.window == period), None)


def _best_holding_period(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> str | None:
    period_returns: dict[str, Decimal] = {}
    for period in _PERIODS:
        returns = tuple(
            window.forward_return_pct_from_close
            for record in records
            if (window := _window(outcomes.get(record.raw_candidate_id), period))
            is not None
            and window.forward_return_pct_from_close is not None
        )
        if (average := _average(returns)) is not None:
            period_returns[period] = average
    if not period_returns:
        return None
    return max(period_returns.items(), key=lambda item: item[1])[0]


def _worst_failure_mode(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> str | None:
    failures: dict[str, int] = {}
    for record in records:
        window = _window(outcomes.get(record.raw_candidate_id), "20d")
        if (
            window is None
            or window.forward_return_pct_from_close is None
            or window.forward_return_pct_from_close >= _ZERO
        ):
            continue
        key = record.exclusion_reasons[0] if record.exclusion_reasons else "loss"
        failures[key] = failures.get(key, 0) + 1
    if not failures:
        return None
    return max(failures.items(), key=lambda item: (item[1], item[0]))[0]


def _disqualification_category(
    decision: OpportunityDecision,
) -> DisqualificationCategory | None:
    if decision.accepted:
        return None
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
    if RejectionReasonCode.INSUFFICIENT_EVIDENCE in codes:
        return DisqualificationCategory.NO_HISTORICAL_EDGE
    if RejectionReasonCode.WEAK_CONFIDENCE in codes:
        return DisqualificationCategory.WEAK_CONFIDENCE
    if (
        RejectionReasonCode.POOR_DATA_COMPLETENESS in codes
        or RejectionReasonCode.INSUFFICIENT_CAPACITY in codes
    ):
        return DisqualificationCategory.DATA_OR_CAPACITY
    return DisqualificationCategory.OTHER


def _price_volume_state(decision: OpportunityDecision) -> str:
    candidate = decision.candidate
    if candidate.bearish_indicator_count > 0:
        return "Bearish contradiction present in price-volume evidence."
    if decision.accepted:
        return "Price-volume evidence supports the trade plan."
    return "Price-volume evidence is not strong enough for deployment."


def _trend_state(decision: OpportunityDecision) -> str:
    scorecard = decision.candidate.setup_scorecard
    if scorecard is None:
        return "Trend state unavailable."
    return f"Trend alignment score is {scorecard.trend_alignment}/100."


def _trade_plan_summary(decision: OpportunityDecision) -> str:
    quality = decision.trade_plan_quality
    if quality is not None and quality.final_selected_plan is not None:
        plan = quality.final_selected_plan
        return (
            f"Entry {plan.entry}, stop {plan.selected_stop}, "
            f"targets {_targets(plan.selected_targets)}, "
            f"reward/risk {plan.reward_risk}."
        )
    candidate = decision.candidate
    targets = _targets((candidate.target_1, candidate.target_2, candidate.target_3))
    return (
        f"Entry {_metric(candidate.entry)}, stop {_metric(candidate.stop)}, "
        f"targets {targets}."
    )


def _investor_summary(
    *,
    symbol: str,
    verdict: RiskCommitteeVerdict,
    reason: str,
    similar: SimilarHistoricalCases,
) -> str:
    evidence = (
        f" Historical evidence has {similar.sample_count} similar completed cases."
        if similar.sample_count
        else " Historical evidence is not yet available for similar cases."
    )
    return f"{symbol}: {verdict.value}. {reason}{evidence}"


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def _evidence_strength(sample_count: int) -> str:
    if sample_count < 10:
        return "insufficient"
    if sample_count < 30:
        return "weak"
    if sample_count < 100:
        return "moderate"
    return "strong"


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _targets(values: tuple[Decimal | None, ...]) -> str:
    available = tuple(value for value in values if value is not None)
    if not available:
        return "unavailable"
    return ", ".join(str(value) for value in available)


__all__ = [
    "DecisionEvidenceCardBuilder",
    "DecisionEvidenceSnapshot",
    "RiskCommitteeGate",
    "RiskCommitteeVerdict",
    "SimilarHistoricalCases",
    "SimilarHistoricalCasesEngine",
    "render_decision_evidence_cards",
]
