from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from alpha.decision_intelligence.models import (
    CapacityAssessment,
    DecisionAuditReport,
    GateDecision,
    InstitutionalCandidate,
    InstitutionalCandidateStageTrace,
    InstitutionalDecisionReport,
    InstitutionalEvaluationResult,
    OpportunityDecision,
    OpportunityGrade,
    OpportunityScoreBreakdown,
    RejectionReason,
    RejectionReasonCode,
    SetupQualityScorecard,
    TradePlanAuditReport,
    opportunity_grade,
)
from alpha.decision_intelligence.stress import DecisionStressTestEngine
from alpha.decision_intelligence.tradeplan import TradePlanOptimizationEngine
from alpha.portfolio_intelligence import CapitalAllocationPlan

_ZERO = Decimal("0")
_MIN_APPROVAL_SAMPLE_COUNT = 60
_MIN_APPROVAL_POSTERIOR = Decimal("0.52")
_MIN_APPROVAL_EXPECTANCY = Decimal("0.10")
_MIN_DEPLOYMENT_SCORE = Decimal("85")
_MAX_DEPLOYMENT_STOP_DISTANCE = Decimal("10")


class InstitutionalDecisionEngine:
    def __init__(
        self,
        *,
        stress_engine: DecisionStressTestEngine | None = None,
        trade_plan_optimizer: TradePlanOptimizationEngine | None = None,
    ) -> None:
        self.stress_engine = stress_engine or DecisionStressTestEngine()
        self.trade_plan_optimizer = (
            trade_plan_optimizer or TradePlanOptimizationEngine()
        )

    def evaluate(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> InstitutionalDecisionReport:
        return self.evaluate_with_trace(candidates).report

    def evaluate_with_trace(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> InstitutionalEvaluationResult:
        """Invoke each authoritative stage exactly once and retain its output."""

        traces: list[InstitutionalCandidateStageTrace] = []
        for candidate in candidates:
            base = self._decision(candidate)
            stressed = self.stress_engine.stress_test(base)
            optimized = self.trade_plan_optimizer.optimize_decision(stressed)
            traces.append(
                InstitutionalCandidateStageTrace(
                    candidate=candidate,
                    base_decision=base,
                    stress_decision=stressed,
                    trade_plan_decision=optimized,
                )
            )
        trace_tuple = tuple(traces)
        return InstitutionalEvaluationResult(
            report=self._report(
                candidates=candidates,
                decisions=tuple(trace.trade_plan_decision for trace in trace_tuple),
            ),
            traces=trace_tuple,
        )

    def _report(
        self,
        *,
        candidates: tuple[InstitutionalCandidate, ...],
        decisions: tuple[OpportunityDecision, ...],
    ) -> InstitutionalDecisionReport:
        accepted = tuple(
            sorted(
                (decision for decision in decisions if decision.accepted),
                key=lambda decision: (
                    -decision.opportunity_score,
                    decision.candidate.symbol,
                ),
            )
        )
        rejected = tuple(decision for decision in decisions if not decision.accepted)
        average_score = (
            None
            if not accepted
            else (
                sum((decision.opportunity_score for decision in accepted), _ZERO)
                / Decimal(len(accepted))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        acceptance_rate = (
            Decimal("0")
            if not decisions
            else (Decimal(len(accepted)) / Decimal(len(decisions))).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )
        return InstitutionalDecisionReport(
            decisions=decisions,
            candidates_scanned=len(candidates),
            accepted_opportunities=accepted,
            rejected_opportunities=rejected,
            acceptance_rate=acceptance_rate,
            average_opportunity_score=average_score,
            concentration_warnings=self._concentration_warnings(accepted),
            evidence_quality_summary=self._evidence_summary(decisions),
            no_trade_reason=None if accepted else "No high-quality trade setup today.",
        )

    def audit(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> DecisionAuditReport:
        return self.stress_engine.audit(self.evaluate(candidates).decisions)

    def trade_plan_audit(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> TradePlanAuditReport:
        return self.trade_plan_optimizer.audit(self.evaluate(candidates).decisions)

    def evaluate_recommendations(
        self,
        recommendations: tuple[object, ...],
        *,
        allocation_plan: CapitalAllocationPlan | None = None,
    ) -> InstitutionalDecisionReport:
        allocation_by_symbol = (
            {report.symbol: report for report in allocation_plan.reports}
            if allocation_plan is not None
            else {}
        )
        candidates = tuple(
            candidate_from_recommendation(
                recommendation,
                allocation_report=allocation_by_symbol.get(
                    getattr(recommendation, "symbol", "")
                ),
            )
            for recommendation in recommendations
        )
        return self.evaluate(candidates)

    def evaluate_recommendations_with_trace(
        self,
        recommendations: tuple[object, ...],
        *,
        allocation_plan: CapitalAllocationPlan | None = None,
    ) -> InstitutionalEvaluationResult:
        """Convert recommendations and retain the authoritative stage trace."""

        allocation_by_symbol = (
            {report.symbol: report for report in allocation_plan.reports}
            if allocation_plan is not None
            else {}
        )
        candidates = tuple(
            candidate_from_recommendation(
                recommendation,
                allocation_report=allocation_by_symbol.get(
                    getattr(recommendation, "symbol", "")
                ),
            )
            for recommendation in recommendations
        )
        return self.evaluate_with_trace(candidates)

    def _decision(self, candidate: InstitutionalCandidate) -> OpportunityDecision:
        if candidate.setup_scorecard is None:
            candidate = replace(
                candidate,
                setup_scorecard=setup_scorecard_from_candidate(candidate),
            )
        rejection_reasons = self._rejection_reasons(candidate)
        accepted = len(rejection_reasons) == 0
        breakdown = self._score_breakdown(candidate)
        score = breakdown.total_score if accepted else Decimal("0.00")
        grade = opportunity_grade(score, accepted=accepted)
        strength = self._primary_strength(breakdown)
        weakness = self._primary_weakness(candidate, breakdown, rejection_reasons)
        return OpportunityDecision(
            candidate=candidate,
            gate_decision=GateDecision.ACCEPT if accepted else GateDecision.REJECT,
            rejection_reasons=tuple(rejection_reasons),
            opportunity_score=score,
            opportunity_grade=grade,
            score_breakdown=breakdown,
            primary_strength=strength,
            primary_weakness=weakness,
            selection_reason=self._selection_reason(candidate, score, grade, accepted),
            portfolio_penalty=Decimal("100") - breakdown.portfolio_fit,
        )

    def _rejection_reasons(
        self,
        candidate: InstitutionalCandidate,
    ) -> list[RejectionReason]:
        reasons: list[RejectionReason] = []
        if candidate.final_verdict not in {"BUY", "STRONG_BUY"}:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.WEAK_VERDICT,
                    "Only BUY or STRONG_BUY candidates are deployable.",
                )
            )
        scorecard = candidate.setup_scorecard or setup_scorecard_from_candidate(
            candidate
        )
        if candidate.setup_stage == "LATE":
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.LATE_ENTRY,
                    "Setup is late; fresh deployment is blocked until a better "
                    "entry forms.",
                )
            )
        if (
            not candidate.entry_ready
            or candidate.trigger_status != "TRIGGER_CONFIRMED"
            or candidate.execution_status not in {"BUY NOW", "BUY_NOW"}
            or not candidate.allocation_eligible
        ):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.PENDING_ENTRY_TRIGGER,
                    "Entry is not actionable yet; capital waits for trigger "
                    "confirmation.",
                )
            )
        if _confidence_rank(candidate.adjusted_confidence) < _confidence_rank("MEDIUM"):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.WEAK_CONFIDENCE,
                    "Adjusted confidence is below institutional threshold.",
                )
            )
        if candidate.final_score < _MIN_DEPLOYMENT_SCORE:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.WEAK_SETUP,
                    "Final evidence score is below the stricter deployment "
                    f"threshold of {_MIN_DEPLOYMENT_SCORE}.",
                )
            )
        if candidate.evidence_strength == "insufficient":
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.INSUFFICIENT_EVIDENCE,
                    "Adaptive evidence is insufficient for fresh deployment.",
                )
            )
        if _has_insufficient_approval_evidence(candidate):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.INSUFFICIENT_EVIDENCE,
                    "Fresh deployment requires at least "
                    f"{_MIN_APPROVAL_SAMPLE_COUNT} completed historical samples "
                    "for the matched setup.",
                )
            )
        if _has_poor_historical_edge(candidate):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.POOR_HISTORICAL_EDGE,
                    "Completed historical evidence for this setup is negative; "
                    "fresh deployment is blocked until the edge improves.",
                )
            )
        if candidate.reward_risk_ratio is None:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.MISSING_TRADE_PLAN,
                    "Reward/risk is unavailable because the trade plan is incomplete.",
                )
            )
        if not _has_complete_deployment_trade_plan(candidate):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.MISSING_TRADE_PLAN,
                    "Fresh deployment requires entry, stop, at least two targets, "
                    "ATR context, and 20-DMA invalidation.",
                )
            )
        elif (
            candidate.reward_risk_ratio is not None
            and candidate.reward_risk_ratio < Decimal("2")
        ):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.POOR_REWARD_RISK,
                    "Reward/risk is below the 2R institutional minimum.",
                )
            )
        if (
            candidate.stop_distance_percent is not None
            and candidate.stop_distance_percent > _MAX_DEPLOYMENT_STOP_DISTANCE
        ):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.EXCESS_DOWNSIDE_RISK,
                    "Initial stop distance is too wide for fresh deployment; "
                    f"maximum allowed is {_MAX_DEPLOYMENT_STOP_DISTANCE}%.",
                )
            )
        if candidate.data_completeness not in {"COMPLETE", "GOOD"}:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.POOR_DATA_COMPLETENESS,
                    "Data completeness is below the required level.",
                )
            )
        if (
            not candidate.capacity.data_sufficient
            or candidate.capacity.capacity_score < Decimal("35")
        ):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.INSUFFICIENT_CAPACITY,
                    "Liquidity or capacity is insufficient for deployment.",
                )
            )
        if candidate.live_feed_healthy is False:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.LIVE_FEED_UNHEALTHY,
                    "Live mode feed health is not acceptable.",
                )
            )
        if candidate.setup_quality in {"WEAK", "LOW", "RANDOM"}:
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.WEAK_SETUP,
                    "Setup quality is too weak for institutional output.",
                )
            )
        if scorecard.total_score < Decimal("70"):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.WEAK_SETUP,
                    "Setup scorecard is below the A/B quality threshold.",
                )
            )
        if scorecard.entry_quality < Decimal("50"):
            reasons.append(
                RejectionReason(
                    RejectionReasonCode.PENDING_ENTRY_TRIGGER,
                    "Entry quality is poor; wait for a cleaner entry zone or trigger.",
                )
            )
        return reasons

    def _score_breakdown(
        self,
        candidate: InstitutionalCandidate,
    ) -> OpportunityScoreBreakdown:
        posterior = (
            None
            if candidate.posterior_probability is None
            else (candidate.posterior_probability * Decimal("100")).quantize(
                Decimal("0.01")
            )
        )
        expectancy = _expectancy_score(candidate.expectancy)
        reward_risk = _reward_risk_score(candidate.reward_risk_ratio)
        stop_distance = _stop_score(candidate.stop_distance_percent)
        data = (
            Decimal("100")
            if candidate.data_completeness in {"COMPLETE", "GOOD"}
            else Decimal("30")
        )
        capacity = candidate.capacity.capacity_score
        market = (
            Decimal("80")
            if candidate.market_regime not in {None, "BEARISH"}
            else Decimal("50")
        )
        sector = (
            candidate.sector_fit if candidate.sector_fit is not None else Decimal("50")
        )
        portfolio = (
            candidate.portfolio_fit
            if candidate.portfolio_fit is not None
            else Decimal("50")
        )
        live = max(
            Decimal("0"),
            Decimal("100") - Decimal(candidate.live_risk_warning_count * 20),
        )
        weighted = (
            ((posterior if posterior is not None else Decimal("40")) * Decimal("0.18"))
            + (
                (expectancy if expectancy is not None else Decimal("35"))
                * Decimal("0.16")
            )
            + (
                (reward_risk if reward_risk is not None else Decimal("0"))
                * Decimal("0.16")
            )
            + (
                (stop_distance if stop_distance is not None else Decimal("35"))
                * Decimal("0.10")
            )
            + (data * Decimal("0.10"))
            + (capacity * Decimal("0.10"))
            + (market * Decimal("0.07"))
            + (sector * Decimal("0.05"))
            + (portfolio * Decimal("0.06"))
            + (live * Decimal("0.02"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return OpportunityScoreBreakdown(
            posterior_probability=posterior,
            expectancy=expectancy,
            reward_risk=reward_risk,
            stop_distance=stop_distance,
            data_completeness=data,
            capacity=capacity,
            market_regime_fit=market,
            sector_fit=sector,
            portfolio_fit=portfolio,
            live_risk=live,
            total_score=weighted,
        )

    def _primary_strength(self, breakdown: OpportunityScoreBreakdown) -> str:
        mapping = breakdown.as_mapping()
        numeric = {
            key: Decimal(value)
            for key, value in mapping.items()
            if value != "unavailable" and key != "total_score"
        }
        if not numeric:
            return "No quantified strength available."
        key, value = max(numeric.items(), key=lambda item: (item[1], item[0]))
        return f"{key.replace('_', ' ').title()} is strongest at {value}."

    def _primary_weakness(
        self,
        candidate: InstitutionalCandidate,
        breakdown: OpportunityScoreBreakdown,
        rejection_reasons: list[RejectionReason],
    ) -> str:
        if rejection_reasons:
            return rejection_reasons[0].explanation
        mapping = breakdown.as_mapping()
        numeric = {
            key: Decimal(value)
            for key, value in mapping.items()
            if value != "unavailable" and key != "total_score"
        }
        if not numeric:
            return "Missing data reduces confidence."
        key, value = min(numeric.items(), key=lambda item: (item[1], item[0]))
        if candidate.missing_data:
            return f"{key.replace('_', ' ').title()} is weakest; missing data exists."
        return f"{key.replace('_', ' ').title()} is weakest at {value}."

    def _selection_reason(
        self,
        candidate: InstitutionalCandidate,
        score: Decimal,
        grade: OpportunityGrade,
        accepted: bool,
    ) -> str:
        if not accepted:
            return "Rejected by institutional gates."
        return (
            f"Selected because {candidate.symbol} passed all gates with grade "
            f"{grade.value} and opportunity score {score}."
        )

    def _concentration_warnings(
        self,
        accepted: tuple[OpportunityDecision, ...],
    ) -> tuple[str, ...]:
        sector_counts = Counter(decision.candidate.sector for decision in accepted)
        return tuple(
            f"Sector concentration warning: {sector} has {count} accepted ideas."
            for sector, count in sorted(sector_counts.items())
            if count > 1
        )

    def _evidence_summary(self, decisions: tuple[OpportunityDecision, ...]) -> str:
        counts = Counter(
            decision.candidate.evidence_strength or "unavailable"
            for decision in decisions
        )
        if not counts:
            return "No candidates scanned."
        return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def candidate_from_recommendation(
    recommendation: object,
    *,
    allocation_report: object | None = None,
) -> InstitutionalCandidate:
    metadata = getattr(recommendation, "metadata", {})
    price = _decimal(metadata.get("price") or metadata.get("current_price"))
    volume = _decimal(metadata.get("volume"))
    average_volume = _decimal(metadata.get("average_volume"))
    capacity = _capacity_from_values(
        price=price,
        volume=volume,
        average_volume=average_volume,
    )
    reward_risk = getattr(recommendation, "risk_reward_ratio", None)
    entry = getattr(recommendation, "entry_price", None) or getattr(
        recommendation,
        "entry_zone_high",
        None,
    )
    stop = getattr(recommendation, "initial_stop_loss", None)
    stop_distance = _stop_distance(entry, stop)
    portfolio_fit = _portfolio_fit(allocation_report)
    setup_stage = getattr(recommendation, "setup_stage", "UNKNOWN")
    trigger_status = getattr(
        getattr(recommendation, "trigger_status", None),
        "value",
        None,
    )
    trigger_status_text = trigger_status or str(
        getattr(recommendation, "trigger_status", "UNKNOWN")
    )
    entry_ready = bool(getattr(recommendation, "setup_entry_ready", False))
    execution_status = _recommendation_execution_status(
        final_signal=getattr(recommendation, "final_signal", "UNKNOWN"),
        setup_stage=setup_stage,
        entry_ready=entry_ready,
        trigger_status=trigger_status_text,
    )
    return InstitutionalCandidate(
        symbol=getattr(recommendation, "symbol", "UNKNOWN"),
        final_verdict=getattr(recommendation, "final_signal", "UNKNOWN"),
        adjusted_confidence=metadata.get(
            "adaptive_adjusted_confidence",
            getattr(recommendation, "confidence", "LOW"),
        ),
        evidence_strength=metadata.get("adaptive_evidence_strength"),
        final_score=getattr(recommendation, "final_score", Decimal("0")),
        reward_risk_ratio=reward_risk,
        stop_distance_percent=stop_distance,
        data_completeness=metadata.get("data_quality", "UNKNOWN"),
        setup_quality=getattr(recommendation, "setup_quality_label", "UNKNOWN"),
        sector=metadata.get("sector", "UNKNOWN"),
        market_regime=None,
        sector_fit=Decimal("70") if metadata.get("sector") else None,
        portfolio_fit=portfolio_fit,
        posterior_probability=_decimal(metadata.get("adaptive_posterior_probability")),
        expectancy=_decimal(metadata.get("adaptive_expectancy")),
        entry=entry,
        stop=stop,
        target_1=getattr(recommendation, "target_1", None),
        target_2=getattr(recommendation, "target_2", None),
        target_3=getattr(recommendation, "target_3", None),
        capacity=capacity,
        support_level=getattr(recommendation, "support_level_used", None),
        swing_low=getattr(recommendation, "swing_low", None),
        dma_20=_trade_plan_decimal(recommendation, "dma_20_invalidation"),
        atr=_trade_plan_decimal(recommendation, "atr_value"),
        resistance_level=_decimal(metadata.get("resistance_level")),
        swing_high=getattr(recommendation, "swing_high", None),
        evidence_sample_count=_optional_int(metadata.get("adaptive_sample_count")),
        recent_similar_failures=_int(metadata.get("recent_similar_failures")),
        conflicting_signal_count=_int(metadata.get("conflicting_signal_count")),
        near_resistance=metadata.get("near_resistance", "").lower() == "true",
        gap_risk=metadata.get("gap_risk", "").lower() == "true",
        missing_data=tuple(getattr(recommendation, "unavailable_reasons", ())),
        setup_stage=setup_stage,
        entry_ready=entry_ready,
        trigger_status=trigger_status_text,
        execution_status=execution_status,
        allocation_eligible=_allocation_eligible(
            final_signal=getattr(recommendation, "final_signal", "UNKNOWN"),
            entry_ready=entry_ready,
            trigger_status=trigger_status_text,
            execution_status=execution_status,
        ),
        historical_bar_count=int(getattr(recommendation, "historical_bar_count", 0)),
        bearish_indicator_count=_bearish_indicator_count(recommendation),
        bearish_indicator_reasons=_bearish_indicator_reasons(recommendation),
    )


def setup_scorecard_from_candidate(
    candidate: InstitutionalCandidate,
) -> SetupQualityScorecard:
    reward_risk = _reward_risk_score(candidate.reward_risk_ratio) or Decimal("0")
    stop_quality = _stop_score(candidate.stop_distance_percent) or Decimal("35")
    entry_quality = _entry_quality(candidate)
    historical = _historical_score(
        evidence_strength=candidate.evidence_strength,
        sample_count=candidate.evidence_sample_count,
        expectancy=candidate.expectancy,
    )
    liquidity = candidate.capacity.capacity_score
    regime = (
        Decimal("80")
        if candidate.market_regime not in {None, "BEARISH"}
        else Decimal("45")
    )
    trend = _quality_label_score(candidate.setup_quality)
    price_volume = max(Decimal("40"), min(Decimal("100"), candidate.final_score))
    target_realism = Decimal("80") if candidate.target_1 is not None else Decimal("20")
    total = (
        trend * Decimal("0.14")
        + price_volume * Decimal("0.16")
        + entry_quality * Decimal("0.16")
        + stop_quality * Decimal("0.12")
        + target_realism * Decimal("0.10")
        + reward_risk * Decimal("0.12")
        + historical * Decimal("0.08")
        + liquidity * Decimal("0.07")
        + regime * Decimal("0.05")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    grade = opportunity_grade(total, accepted=total >= Decimal("60"))
    return SetupQualityScorecard(
        trend_alignment=trend,
        price_volume_confirmation=price_volume,
        entry_quality=entry_quality,
        stop_quality=stop_quality,
        target_realism=target_realism,
        reward_risk_quality=reward_risk,
        historical_evidence=historical,
        liquidity_capacity=liquidity,
        market_regime_fit=regime,
        total_score=total,
        setup_grade=grade,
        summary=_scorecard_summary(total=total, entry_quality=entry_quality),
    )


def _capacity_from_values(
    *,
    price: Decimal | None,
    volume: Decimal | None,
    average_volume: Decimal | None,
) -> CapacityAssessment:
    from alpha.decision_intelligence.capacity import CapacityAssessor

    return CapacityAssessor().assess(
        price=price,
        volume=volume,
        average_volume=average_volume,
    )


def _confidence_rank(value: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(value.strip().upper(), 0)


def _expectancy_score(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return max(Decimal("0"), min(Decimal("100"), Decimal("50") + value * Decimal("20")))


def _reward_risk_score(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return max(Decimal("0"), min(Decimal("100"), value / Decimal("4") * Decimal("100")))


def _stop_score(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return max(Decimal("0"), Decimal("100") - (value * Decimal("5")))


def _stop_distance(entry: Decimal | None, stop: Decimal | None) -> Decimal | None:
    if entry is None or stop is None or entry <= Decimal("0"):
        return None
    return ((entry - stop) / entry * Decimal("100")).quantize(Decimal("0.01"))


def _portfolio_fit(allocation_report: object | None) -> Decimal | None:
    if allocation_report is None:
        return None
    target_weight = getattr(allocation_report, "target_weight", Decimal("0"))
    if target_weight <= Decimal("0"):
        return Decimal("25")
    return Decimal("80")


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _trade_plan_decimal(recommendation: object, name: str) -> Decimal | None:
    trade_plan = getattr(recommendation, "trade_plan", None)
    if trade_plan is None:
        return None
    return _decimal(getattr(trade_plan, name, None))


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _int(value: object) -> int:
    return _optional_int(value) or 0


def _bearish_indicator_count(recommendation: object) -> int:
    return len(_bearish_indicator_reasons(recommendation))


def _bearish_indicator_reasons(recommendation: object) -> tuple[str, ...]:
    reasons: list[str] = []
    final_signal = str(getattr(recommendation, "final_signal", "")).upper()
    if final_signal in {"SELL", "STRONG_SELL", "AVOID", "REJECT"}:
        reasons.append(f"Final signal is {final_signal}.")
    for risk in getattr(recommendation, "opposing_evidence", ()):
        label = getattr(risk, "label", "Risk")
        rationale = getattr(risk, "rationale", "")
        reasons.append(f"{label}: {rationale}".strip())
    price = getattr(recommendation, "price_evidence", None)
    if price is not None:
        if getattr(price, "breakout_state", "") == "BREAKDOWN":
            reasons.append("Price evidence shows breakdown.")
        if getattr(price, "structure_state", "") in {"LOWER_LOW", "DISTRIBUTION"}:
            reasons.append("Price structure is bearish.")
    volume = getattr(recommendation, "volume_evidence", None)
    if volume is not None and getattr(
        volume, "selloff_volume_penalty", Decimal("0")
    ) >= Decimal("0.70"):
        reasons.append("Volume evidence shows heavy selloff pressure.")
    candle = str(getattr(recommendation, "candle_confirmation", "")).upper()
    if "BEARISH" in candle or "WARNING" in candle:
        reasons.append(f"Candle confirmation is {candle}.")
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def _recommendation_execution_status(
    *,
    final_signal: str,
    setup_stage: str,
    entry_ready: bool,
    trigger_status: str,
) -> str:
    signal = final_signal.strip().upper()
    stage = setup_stage.strip().upper()
    trigger = trigger_status.strip().upper()
    if signal in {"AVOID", "SELL", "REJECT"} or stage == "INVALID":
        return "AVOID"
    if (
        entry_ready
        and stage in {"ENTRY_READY", "ACTIVE"}
        and trigger == "TRIGGER_CONFIRMED"
    ):
        return "BUY NOW"
    if stage == "LATE":
        return "HOLD / NO FRESH ENTRY"
    return "WAIT FOR CONFIRMATION"


def _allocation_eligible(
    *,
    final_signal: str,
    entry_ready: bool,
    trigger_status: str,
    execution_status: str,
) -> bool:
    return (
        final_signal.strip().upper() in {"BUY", "STRONG_BUY"}
        and entry_ready
        and trigger_status.strip().upper() == "TRIGGER_CONFIRMED"
        and execution_status == "BUY NOW"
    )


def _entry_quality(candidate: InstitutionalCandidate) -> Decimal:
    if candidate.setup_stage == "LATE":
        return Decimal("20")
    if not candidate.entry_ready or candidate.trigger_status != "TRIGGER_CONFIRMED":
        return Decimal("45")
    if candidate.entry is None or candidate.stop is None:
        return Decimal("25")
    if candidate.stop_distance_percent is not None:
        if candidate.stop_distance_percent > Decimal("12"):
            return Decimal("35")
        if candidate.stop_distance_percent <= Decimal("8"):
            return Decimal("90")
    return Decimal("75")


def _historical_score(
    *,
    evidence_strength: str | None,
    sample_count: int | None,
    expectancy: Decimal | None,
) -> Decimal:
    strength_text = (evidence_strength or "").strip().upper()
    if strength_text in {"INSUFFICIENT", "INSUFFICIENT_SAMPLE", ""}:
        return Decimal("35")
    base = {
        "WEAK": Decimal("50"),
        "MODERATE": Decimal("70"),
        "STRONG": Decimal("85"),
    }.get(strength_text, Decimal("45"))
    if sample_count is not None and sample_count < 30:
        base = min(base, Decimal("55"))
    if expectancy is not None:
        base += max(Decimal("-20"), min(Decimal("15"), expectancy * Decimal("5")))
    return max(Decimal("0"), min(Decimal("100"), base))


def _has_poor_historical_edge(candidate: InstitutionalCandidate) -> bool:
    if candidate.evidence_sample_count is None or candidate.evidence_sample_count < 30:
        return False
    if (
        candidate.expectancy is not None
        and candidate.expectancy < _MIN_APPROVAL_EXPECTANCY
    ):
        return True
    return (
        candidate.posterior_probability is not None
        and candidate.posterior_probability < _MIN_APPROVAL_POSTERIOR
    )


def _has_insufficient_approval_evidence(candidate: InstitutionalCandidate) -> bool:
    if candidate.evidence_strength in {"strong", "STRONG"}:
        return False
    return (
        candidate.evidence_sample_count is None
        or candidate.evidence_sample_count < _MIN_APPROVAL_SAMPLE_COUNT
    )


def _has_complete_deployment_trade_plan(candidate: InstitutionalCandidate) -> bool:
    return all(
        value is not None
        for value in (
            candidate.entry,
            candidate.stop,
            candidate.target_1,
            candidate.target_2,
            candidate.reward_risk_ratio,
            candidate.dma_20,
            candidate.atr,
        )
    )


def _quality_label_score(value: str) -> Decimal:
    return {
        "EXCELLENT": Decimal("95"),
        "HIGH": Decimal("88"),
        "GOOD": Decimal("78"),
        "MEDIUM": Decimal("65"),
        "FAIR": Decimal("58"),
        "LOW": Decimal("35"),
        "WEAK": Decimal("25"),
        "RANDOM": Decimal("20"),
    }.get(value.strip().upper(), Decimal("55"))


def _scorecard_summary(*, total: Decimal, entry_quality: Decimal) -> str:
    if total >= Decimal("80") and entry_quality >= Decimal("70"):
        return "High-quality setup with actionable entry and controlled risk."
    if entry_quality < Decimal("50"):
        return "Constructive idea may exist, but entry quality is not actionable yet."
    if total >= Decimal("70"):
        return "Tradable setup if portfolio risk limits allow deployment."
    return "Setup needs better evidence, entry quality, or risk/reward."


__all__ = [
    "InstitutionalDecisionEngine",
    "candidate_from_recommendation",
    "setup_scorecard_from_candidate",
]
