from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from alpha.decision_intelligence.models import (
    DecisionAuditReport,
    DecisionQualityAssessment,
    FinalDecisionAction,
    InstitutionalCandidate,
    OpportunityDecision,
    OverconfidenceAssessment,
    StopQuality,
    StopQualityAssessment,
    StressDecisionAction,
    StressReasonCode,
    StressSeverity,
    StressTestResult,
    TargetQuality,
    TargetQualityAssessment,
    opportunity_grade,
)


class DecisionStressTestEngine:
    def stress_test(
        self,
        decision: OpportunityDecision,
    ) -> OpportunityDecision:
        if not decision.accepted:
            return decision
        candidate = decision.candidate
        stop_quality = StopQualityReview().assess(candidate)
        target_quality = TargetQualityReview().assess(candidate)
        overconfidence = OverconfidenceGuard().assess(candidate)
        stress_tests = self._stress_tests(
            candidate=candidate,
            stop_quality=stop_quality,
            target_quality=target_quality,
            overconfidence=overconfidence,
        )
        quality = self._quality(
            decision=decision,
            stress_tests=stress_tests,
            stop_quality=stop_quality,
            target_quality=target_quality,
            overconfidence=overconfidence,
        )
        return OpportunityDecision(
            candidate=decision.candidate,
            gate_decision=decision.gate_decision,
            rejection_reasons=decision.rejection_reasons,
            opportunity_score=decision.opportunity_score,
            opportunity_grade=decision.opportunity_grade,
            score_breakdown=decision.score_breakdown,
            primary_strength=decision.primary_strength,
            primary_weakness=decision.primary_weakness,
            selection_reason=decision.selection_reason,
            portfolio_penalty=decision.portfolio_penalty,
            stress_tests=stress_tests,
            decision_quality=quality,
        )

    def audit(self, decisions: tuple[OpportunityDecision, ...]) -> DecisionAuditReport:
        quality_scores = tuple(
            decision.decision_quality.decision_quality_score
            for decision in decisions
            if decision.decision_quality is not None
        )
        failure_modes = Counter(
            result.reason_code
            for decision in decisions
            for result in decision.stress_tests
            if not result.passed
        )
        stop_distribution = Counter(
            decision.decision_quality.stop_quality.stop_quality.value
            for decision in decisions
            if decision.decision_quality is not None
        )
        target_distribution = Counter(
            decision.decision_quality.target_quality.target_quality.value
            for decision in decisions
            if decision.decision_quality is not None
        )
        accepted_before = sum(
            1 for decision in decisions if decision.gate_decision.value == "ACCEPT"
        )
        accepted_after = sum(
            1
            for decision in decisions
            if decision.decision_quality is not None
            and decision.decision_quality.final_action is FinalDecisionAction.ACCEPT
        )
        downgraded = sum(1 for decision in decisions if decision.downgraded)
        rejected_by_stress = sum(
            1
            for decision in decisions
            if decision.gate_decision.value == "ACCEPT"
            and decision.decision_quality is not None
            and decision.decision_quality.final_action is not FinalDecisionAction.ACCEPT
        )
        average_score = (
            None
            if not quality_scores
            else (
                sum(quality_scores, Decimal("0")) / Decimal(len(quality_scores))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        return DecisionAuditReport(
            candidates_scanned=len(decisions),
            institutional_accepted_before_stress=accepted_before,
            final_accepted_after_stress=accepted_after,
            downgraded=downgraded,
            rejected_by_stress=rejected_by_stress,
            top_failure_modes=tuple(failure_modes.most_common(5)),
            average_decision_quality_score=average_score,
            stop_quality_distribution=MappingProxyType(dict(stop_distribution)),
            target_quality_distribution=MappingProxyType(dict(target_distribution)),
            overconfidence_reductions=sum(
                1
                for decision in decisions
                if decision.decision_quality is not None
                and decision.decision_quality.overconfidence.reduction_applied
            ),
            no_trade_explanation="No high-quality trade setup today."
            if accepted_after == 0
            else None,
        )

    def _stress_tests(
        self,
        *,
        candidate: InstitutionalCandidate,
        stop_quality: StopQualityAssessment,
        target_quality: TargetQualityAssessment,
        overconfidence: OverconfidenceAssessment,
    ) -> tuple[StressTestResult, ...]:
        tests = [
            self._weak_evidence_high_score(candidate),
            self._high_confidence_low_sample(candidate),
            self._poor_reward_risk(candidate),
            self._bad_regime(candidate),
            self._sector_crowding(candidate),
            self._excessive_volatility(candidate),
            self._low_capacity(candidate),
            self._stale_or_incomplete_data(candidate),
            self._stop_too_close(candidate, stop_quality),
            self._stop_too_wide(candidate, stop_quality),
            self._target_too_optimistic(candidate, target_quality),
            self._concentration(candidate),
            self._conflicting_signals(candidate),
            self._recent_failed_similar_setup(candidate),
            self._fragile_near_resistance(candidate),
            self._gap_risk(candidate),
            self._buy_contradicted_by_sell_indicators(candidate),
            self._insufficient_five_year_history(candidate),
        ]
        if overconfidence.reduction_applied:
            tests.append(
                StressTestResult(
                    passed=False,
                    severity=StressSeverity.MEDIUM,
                    reason_code=StressReasonCode.HIGH_CONFIDENCE_LOW_SAMPLE,
                    explanation=overconfidence.explanation,
                    suggested_action=StressDecisionAction.DOWNGRADE,
                )
            )
        return tuple(tests)

    def _quality(
        self,
        *,
        decision: OpportunityDecision,
        stress_tests: tuple[StressTestResult, ...],
        stop_quality: StopQualityAssessment,
        target_quality: TargetQualityAssessment,
        overconfidence: OverconfidenceAssessment,
    ) -> DecisionQualityAssessment:
        failed = tuple(result for result in stress_tests if not result.passed)
        penalty = sum(
            (_severity_penalty(result.severity) for result in failed),
            Decimal("0"),
        )
        quality_bonus = _quality_bonus(stop_quality.stop_quality)
        target_bonus = _quality_bonus(target_quality.target_quality)
        score = max(
            Decimal("0"),
            min(
                Decimal("100"),
                decision.opportunity_score
                - penalty
                - overconfidence.penalty_points
                + quality_bonus
                + target_bonus,
            ),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        final_action = _final_action(
            score=score,
            failed=failed,
            stop_quality=stop_quality,
            target_quality=target_quality,
        )
        warnings = tuple(result.explanation for result in failed[:3])
        return DecisionQualityAssessment(
            decision_quality_score=score,
            decision_quality_grade=opportunity_grade(
                score,
                accepted=final_action is FinalDecisionAction.ACCEPT,
            ),
            final_action=final_action,
            top_risk_warnings=warnings or ("No major stress-test warnings.",),
            stress_penalty=penalty,
            stop_quality=stop_quality,
            target_quality=target_quality,
            overconfidence=overconfidence,
        )

    def _weak_evidence_high_score(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.evidence_strength in {
            "weak",
            "insufficient",
            None,
        } and candidate.final_score >= Decimal("80")
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.WEAK_EVIDENCE_HIGH_SCORE,
            explanation="High technical score is not backed by strong evidence.",
            action=StressDecisionAction.DOWNGRADE,
        )

    def _high_confidence_low_sample(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        samples = candidate.evidence_sample_count
        failed = candidate.adjusted_confidence == "HIGH" and (
            samples is None or samples < 10
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.HIGH_CONFIDENCE_LOW_SAMPLE,
            explanation="High confidence has too few completed outcome samples.",
            action=StressDecisionAction.DOWNGRADE,
        )

    def _poor_reward_risk(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = (
            candidate.reward_risk_ratio is None
            or candidate.reward_risk_ratio < Decimal("2.5")
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.POOR_REWARD_RISK,
            explanation="Reward/risk is too marginal after stress testing.",
            action=StressDecisionAction.REJECT,
        )

    def _bad_regime(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = candidate.market_regime == "BEARISH"
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.BAD_MARKET_REGIME,
            explanation="Setup is technically good but market regime is unfavorable.",
            action=StressDecisionAction.DOWNGRADE,
        )

    def _sector_crowding(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = candidate.sector_fit is not None and candidate.sector_fit < Decimal(
            "45"
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.SECTOR_CROWDING,
            explanation="Sector crowding reduces fresh deployment quality.",
            action=StressDecisionAction.REDUCE_SIZE,
        )

    def _excessive_volatility(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = (
            candidate.stop_distance_percent is not None
            and candidate.stop_distance_percent > Decimal("10")
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.EXCESSIVE_VOLATILITY,
            explanation="Stop distance implies elevated volatility risk.",
            action=StressDecisionAction.REDUCE_SIZE,
        )

    def _low_capacity(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = candidate.capacity.capacity_score < Decimal("50")
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.LOW_CAPACITY,
            explanation="Capacity is not strong enough after stress testing.",
            action=StressDecisionAction.REJECT,
        )

    def _stale_or_incomplete_data(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.data_completeness != "COMPLETE" or bool(
            candidate.missing_data
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.STALE_OR_INCOMPLETE_DATA,
            explanation="Incomplete or stale data weakens the decision.",
            action=StressDecisionAction.REJECT,
        )

    def _stop_too_close(
        self,
        candidate: InstitutionalCandidate,
        stop_quality: StopQualityAssessment,
    ) -> StressTestResult:
        failed = (
            stop_quality.stop_quality is StopQuality.INVALID
            and candidate.stop_distance_percent is not None
            and candidate.stop_distance_percent < Decimal("2")
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.CRITICAL,
            reason_code=StressReasonCode.STOP_TOO_CLOSE,
            explanation="Stop is too tight for normal volatility.",
            action=StressDecisionAction.REJECT,
        )

    def _stop_too_wide(
        self,
        candidate: InstitutionalCandidate,
        stop_quality: StopQualityAssessment,
    ) -> StressTestResult:
        failed = (
            stop_quality.stop_quality is StopQuality.INVALID
            and candidate.stop_distance_percent is not None
            and candidate.stop_distance_percent > Decimal("12")
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.CRITICAL,
            reason_code=StressReasonCode.STOP_TOO_WIDE,
            explanation="Stop is too wide for acceptable position sizing.",
            action=StressDecisionAction.REJECT,
        )

    def _target_too_optimistic(
        self,
        candidate: InstitutionalCandidate,
        target_quality: TargetQualityAssessment,
    ) -> StressTestResult:
        failed = target_quality.target_quality is TargetQuality.WEAK
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.TARGET_TOO_OPTIMISTIC,
            explanation="Target depends on an unusually large move.",
            action=StressDecisionAction.LOWER_TARGET,
        )

    def _concentration(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = (
            candidate.portfolio_fit is not None
            and candidate.portfolio_fit < Decimal("45")
        )
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.CORRELATION_CONCENTRATION,
            explanation="Portfolio fit indicates concentration or correlation risk.",
            action=StressDecisionAction.REDUCE_SIZE,
        )

    def _conflicting_signals(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.conflicting_signal_count > 0
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.CONFLICTING_SIGNALS,
            explanation="Decision has unresolved conflicting signals.",
            action=StressDecisionAction.DOWNGRADE,
        )

    def _recent_failed_similar_setup(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.recent_similar_failures > 0
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.RECENT_FAILED_SIMILAR_SETUP,
            explanation="Recent similar setup failed in the recommendation ledger.",
            action=StressDecisionAction.REJECT,
        )

    def _fragile_near_resistance(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.near_resistance
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.FRAGILE_NEAR_RESISTANCE,
            explanation="Setup is fragile near resistance.",
            action=StressDecisionAction.REJECT,
        )

    def _gap_risk(self, candidate: InstitutionalCandidate) -> StressTestResult:
        failed = candidate.gap_risk
        return _result(
            passed=not failed,
            severity=StressSeverity.MEDIUM,
            reason_code=StressReasonCode.GAP_RISK,
            explanation="Gap-risk vulnerability increases execution uncertainty.",
            action=StressDecisionAction.DOWNGRADE,
        )

    def _buy_contradicted_by_sell_indicators(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = (
            candidate.final_verdict in {"BUY", "STRONG_BUY"}
            and candidate.bearish_indicator_count >= 3
        )
        reasons = "; ".join(candidate.bearish_indicator_reasons[:3])
        return _result(
            passed=not failed,
            severity=StressSeverity.CRITICAL,
            reason_code=StressReasonCode.BUY_CONTRADICTED_BY_SELL_INDICATORS,
            explanation=(
                "BUY is contradicted by sell-side indicator evidence"
                + (f": {reasons}" if reasons else ".")
            ),
            action=StressDecisionAction.REJECT,
        )

    def _insufficient_five_year_history(
        self,
        candidate: InstitutionalCandidate,
    ) -> StressTestResult:
        failed = candidate.historical_bar_count < 1260
        return _result(
            passed=not failed,
            severity=StressSeverity.HIGH,
            reason_code=StressReasonCode.INSUFFICIENT_FIVE_YEAR_HISTORY,
            explanation=(
                "Less than five years of historical bars are available for "
                f"pattern evidence ({candidate.historical_bar_count}/1260)."
            ),
            action=StressDecisionAction.REJECT,
        )


class StopQualityReview:
    def assess(self, candidate: InstitutionalCandidate) -> StopQualityAssessment:
        distance = candidate.stop_distance_percent
        if distance is None:
            return StopQualityAssessment(
                stop_quality=StopQuality.INVALID,
                recommended_adjustment="Record a numeric entry and stop.",
                explanation="Stop quality cannot be evaluated without stop distance.",
            )
        if distance < Decimal("2"):
            return StopQualityAssessment(
                stop_quality=StopQuality.INVALID,
                recommended_adjustment=(
                    "Widen stop beyond normal noise or reject setup."
                ),
                explanation="Stop is unrealistically tight versus normal volatility.",
            )
        if distance > Decimal("12"):
            return StopQualityAssessment(
                stop_quality=StopQuality.INVALID,
                recommended_adjustment="Reduce risk or reject setup.",
                explanation="Stop is too wide for acceptable position sizing.",
            )
        if distance > Decimal("9"):
            return StopQualityAssessment(
                stop_quality=StopQuality.WEAK,
                recommended_adjustment="Reduce size or wait for a tighter entry.",
                explanation="Stop is wide and weakens risk efficiency.",
            )
        if distance < Decimal("3"):
            return StopQualityAssessment(
                stop_quality=StopQuality.WEAK,
                recommended_adjustment="Confirm stop is below structure.",
                explanation="Stop may be too close to routine volatility.",
            )
        if distance <= Decimal("7"):
            return StopQualityAssessment(
                stop_quality=StopQuality.GOOD,
                recommended_adjustment=None,
                explanation="Stop distance is risk-efficient.",
            )
        return StopQualityAssessment(
            stop_quality=StopQuality.ACCEPTABLE,
            recommended_adjustment="Use reduced size if volatility expands.",
            explanation="Stop distance is acceptable but not ideal.",
        )


class TargetQualityReview:
    def assess(self, candidate: InstitutionalCandidate) -> TargetQualityAssessment:
        ratio = candidate.reward_risk_ratio
        if ratio is None or ratio < Decimal("2"):
            return TargetQualityAssessment(
                target_quality=TargetQuality.INVALID,
                recommended_adjustment="Require at least 2R before considering entry.",
                explanation="Target quality is invalid without acceptable reward/risk.",
            )
        if ratio > Decimal("5"):
            return TargetQualityAssessment(
                target_quality=TargetQuality.WEAK,
                recommended_adjustment="Prefer partial profit or lower the target.",
                explanation="Target appears too optimistic for a primary plan.",
            )
        if ratio >= Decimal("3"):
            return TargetQualityAssessment(
                target_quality=TargetQuality.GOOD,
                recommended_adjustment=None,
                explanation="Target has clean reward/risk.",
            )
        return TargetQualityAssessment(
            target_quality=TargetQuality.ACCEPTABLE,
            recommended_adjustment="Prefer partial profit at Target 1.",
            explanation="Target is acceptable but not exceptional.",
        )


class OverconfidenceGuard:
    def assess(self, candidate: InstitutionalCandidate) -> OverconfidenceAssessment:
        penalty = Decimal("0")
        reasons: list[str] = []
        adjusted = candidate.adjusted_confidence
        if candidate.evidence_strength in {"weak", "insufficient", None}:
            penalty += Decimal("10")
            reasons.append("evidence strength is weak")
        if (
            candidate.evidence_sample_count is None
            or candidate.evidence_sample_count < 10
        ):
            penalty += Decimal("8")
            reasons.append("sample count is low")
        if candidate.data_completeness != "COMPLETE":
            penalty += Decimal("8")
            reasons.append("data completeness is imperfect")
        if candidate.live_risk_warning_count > 0:
            penalty += Decimal("5")
            reasons.append("live/feed risk exists")
        if candidate.market_regime == "BEARISH":
            penalty += Decimal("6")
            reasons.append("market regime is unfavorable")
        if candidate.recent_similar_failures > 0:
            penalty += Decimal("10")
            reasons.append("recent similar outcomes failed")
        if penalty > Decimal("0") and adjusted == "HIGH":
            adjusted = "MEDIUM"
        return OverconfidenceAssessment(
            base_confidence=candidate.adjusted_confidence,
            adjusted_confidence=adjusted,
            reduction_applied=adjusted != candidate.adjusted_confidence,
            penalty_points=min(penalty, Decimal("40")),
            explanation="; ".join(reasons) if reasons else "No overconfidence penalty.",
        )


def _result(
    *,
    passed: bool,
    severity: StressSeverity,
    reason_code: StressReasonCode,
    explanation: str,
    action: StressDecisionAction,
) -> StressTestResult:
    return StressTestResult(
        passed=passed,
        severity=severity,
        reason_code=reason_code,
        explanation=explanation if not passed else f"Passed: {explanation}",
        suggested_action=StressDecisionAction.KEEP if passed else action,
    )


def _severity_penalty(severity: StressSeverity) -> Decimal:
    return {
        StressSeverity.LOW: Decimal("3"),
        StressSeverity.MEDIUM: Decimal("8"),
        StressSeverity.HIGH: Decimal("16"),
        StressSeverity.CRITICAL: Decimal("35"),
    }[severity]


def _quality_bonus(value: StopQuality | TargetQuality) -> Decimal:
    if value.value == "good":
        return Decimal("2")
    if value.value == "acceptable":
        return Decimal("0")
    if value.value == "weak":
        return Decimal("-5")
    return Decimal("-20")


def _final_action(
    *,
    score: Decimal,
    failed: tuple[StressTestResult, ...],
    stop_quality: StopQualityAssessment,
    target_quality: TargetQualityAssessment,
) -> FinalDecisionAction:
    if any(result.severity is StressSeverity.CRITICAL for result in failed):
        return FinalDecisionAction.REJECT
    if any(result.suggested_action is StressDecisionAction.REJECT for result in failed):
        return FinalDecisionAction.REJECT
    if stop_quality.stop_quality is StopQuality.INVALID:
        return FinalDecisionAction.REJECT
    if target_quality.target_quality is TargetQuality.INVALID:
        return FinalDecisionAction.REJECT
    if score < Decimal("70"):
        if score >= Decimal("55") and all(
            result.suggested_action
            in {
                StressDecisionAction.DOWNGRADE,
                StressDecisionAction.REDUCE_SIZE,
                StressDecisionAction.LOWER_TARGET,
                StressDecisionAction.TIGHTEN_STOP,
                StressDecisionAction.WIDEN_STOP,
            }
            for result in failed
        ):
            return FinalDecisionAction.DOWNGRADE
        return FinalDecisionAction.REJECT
    if failed or score < Decimal("80"):
        return FinalDecisionAction.DOWNGRADE
    return FinalDecisionAction.ACCEPT


__all__ = [
    "DecisionStressTestEngine",
    "OverconfidenceGuard",
    "StopQualityReview",
    "TargetQualityReview",
]
