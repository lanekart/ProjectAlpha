from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from alpha.decision_intelligence.models import (
    ExitStrategyAssessment,
    ExitStrategyType,
    FinalDecisionAction,
    InstitutionalCandidate,
    OpportunityDecision,
    OptimizedTradePlan,
    PartialProfitPlan,
    StopCandidate,
    StopQuality,
    TargetCandidate,
    TargetQuality,
    TradePlanAuditReport,
    TradePlanQualityAssessment,
    opportunity_grade,
)


class TradePlanOptimizationEngine:
    def optimize_decision(self, decision: OpportunityDecision) -> OpportunityDecision:
        if not decision.accepted:
            return decision
        assessment = self.assess(decision.candidate)
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
            stress_tests=decision.stress_tests,
            decision_quality=decision.decision_quality,
            trade_plan_quality=assessment,
        )

    def assess(self, candidate: InstitutionalCandidate) -> TradePlanQualityAssessment:
        stops = self.stop_candidates(candidate)
        accepted_stops = tuple(stop for stop in stops if stop.accepted)
        targets = self.target_candidates(candidate)
        accepted_targets = tuple(target for target in targets if target.accepted)
        exit_strategies = self.exit_strategy_comparison(candidate)
        selected_exit = max(
            exit_strategies,
            key=lambda item: (
                item.expected_r if item.expected_r is not None else Decimal("-99"),
                -item.uncertainty_penalty,
                item.strategy_type.value,
            ),
        )
        selected_stop = (
            max(
                accepted_stops,
                key=lambda item: (
                    _stop_quality_score(item.quality),
                    _stop_structure_rank(item.name),
                    item.reward_risk or Decimal("0"),
                    -(item.risk_percent or Decimal("99")),
                ),
            )
            if accepted_stops
            else None
        )
        selected_target = (
            max(
                accepted_targets,
                key=lambda item: (
                    _target_quality_score(item.quality),
                    item.reward_risk or Decimal("0"),
                ),
            )
            if accepted_targets
            else None
        )
        weaknesses = self._weaknesses(
            candidate=candidate,
            selected_stop=selected_stop,
            selected_target=selected_target,
            selected_exit=selected_exit,
        )
        plan = self._optimized_plan(
            candidate=candidate,
            selected_stop=selected_stop,
            selected_target=selected_target,
            selected_exit=selected_exit,
        )
        score = self._quality_score(
            candidate=candidate,
            stop=selected_stop,
            target=selected_target,
            exit_strategy=selected_exit,
        )
        action = (
            FinalDecisionAction.REJECT
            if plan is None or score < Decimal("70")
            else FinalDecisionAction.ACCEPT
        )
        return TradePlanQualityAssessment(
            trade_plan_quality_score=score,
            trade_plan_grade=opportunity_grade(
                score,
                accepted=action is FinalDecisionAction.ACCEPT,
            ),
            final_action=action,
            final_selected_plan=plan,
            stop_quality=(
                selected_stop.quality if selected_stop else StopQuality.INVALID
            ),
            stop_confidence=_confidence_from_quality(
                selected_stop.quality if selected_stop else StopQuality.INVALID
            ),
            target_quality=selected_target.quality
            if selected_target
            else TargetQuality.INVALID,
            target_confidence=_confidence_from_quality(
                selected_target.quality if selected_target else TargetQuality.INVALID
            ),
            weaknesses=weaknesses,
            rejected_stop_candidates=tuple(stop for stop in stops if not stop.accepted),
            rejected_target_candidates=tuple(
                target for target in targets if not target.accepted
            ),
            exit_strategy_comparison=tuple(
                _mark_selected(strategy, selected_exit.strategy_type)
                for strategy in exit_strategies
            ),
            quality_breakdown=MappingProxyType(
                {
                    "stop_quality": str(
                        _stop_quality_score(selected_stop.quality)
                        if selected_stop
                        else Decimal("0")
                    ),
                    "target_quality": str(
                        _target_quality_score(selected_target.quality)
                        if selected_target
                        else Decimal("0")
                    ),
                    "exit_strategy": str(selected_exit.expected_r or Decimal("0")),
                    "reward_risk": str(
                        selected_target.reward_risk
                        if selected_target and selected_target.reward_risk is not None
                        else "unavailable"
                    ),
                    "capacity": str(candidate.capacity.capacity_score),
                }
            ),
        )

    def stop_candidates(
        self,
        candidate: InstitutionalCandidate,
    ) -> tuple[StopCandidate, ...]:
        entry = candidate.entry
        levels: list[tuple[str, Decimal | None]] = [
            ("default", candidate.stop),
            ("tighter stop", _offset(entry, Decimal("0.97"))),
            ("wider volatility stop", _offset(entry, Decimal("0.91"))),
            ("support stop", candidate.support_level),
            ("swing-low stop", candidate.swing_low),
            ("20-DMA stop", candidate.dma_20),
            ("ATR stop", _atr_stop(entry, candidate.atr)),
        ]
        return tuple(
            self._stop_candidate(candidate, name=name, level=level)
            for name, level in levels
        )

    def target_candidates(
        self,
        candidate: InstitutionalCandidate,
    ) -> tuple[TargetCandidate, ...]:
        base_targets = tuple(
            target
            for target in (candidate.target_1, candidate.target_2, candidate.target_3)
            if target is not None
        )
        conservative = tuple(base_targets[:2])
        aggressive = base_targets
        resistance = tuple(
            target
            for target in (candidate.resistance_level, candidate.swing_high)
            if target is not None
        )
        return tuple(
            self._target_candidate(candidate, name=name, targets=targets)
            for name, targets in (
                ("default", base_targets),
                ("conservative target", conservative),
                ("aggressive target", aggressive),
                ("resistance target", resistance),
                ("partial-profit target", conservative),
            )
        )

    def exit_strategy_comparison(
        self,
        candidate: InstitutionalCandidate,
    ) -> tuple[ExitStrategyAssessment, ...]:
        sample_count = candidate.evidence_sample_count
        uncertainty = (
            Decimal("12") if sample_count is None or sample_count < 10 else Decimal("3")
        )
        reward = candidate.reward_risk_ratio
        win_rate = candidate.posterior_probability
        base_expected = (
            None
            if reward is None or win_rate is None
            else ((win_rate * reward) - (Decimal("1") - win_rate)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        )
        return (
            _strategy(
                ExitStrategyType.FIXED_TARGET,
                base_expected,
                win_rate,
                candidate.stop_distance_percent,
                sample_count,
                uncertainty,
                "Fixed target exit uses the selected target set.",
            ),
            _strategy(
                ExitStrategyType.PARTIAL_PROFIT_RUNNER,
                _plus(base_expected, Decimal("0.15")),
                win_rate,
                candidate.stop_distance_percent,
                sample_count,
                max(uncertainty - Decimal("2"), Decimal("0")),
                "Partial profit reduces downside after Target 1.",
            ),
            _strategy(
                ExitStrategyType.TRAILING_AFTER_TARGET_1,
                _plus(base_expected, Decimal("0.10")),
                win_rate,
                candidate.stop_distance_percent,
                sample_count,
                uncertainty,
                "Trailing stop after Target 1 keeps upside open.",
            ),
            _strategy(
                ExitStrategyType.TIME_BASED,
                _minus(base_expected, Decimal("0.20")),
                win_rate,
                candidate.stop_distance_percent,
                sample_count,
                uncertainty + Decimal("2"),
                "Time-based exit is a fallback when targets are slow.",
            ),
            _strategy(
                ExitStrategyType.INVALIDATION,
                _minus(base_expected, Decimal("0.10")),
                win_rate,
                candidate.stop_distance_percent,
                sample_count,
                uncertainty,
                "Invalidation exit follows the original setup failure level.",
            ),
        )

    def audit(
        self,
        decisions: tuple[OpportunityDecision, ...],
    ) -> TradePlanAuditReport:
        reviewed = tuple(
            decision
            for decision in decisions
            if decision.decision_quality is not None
            and decision.decision_quality.final_action.value == "accept"
        )
        optimized = tuple(
            self.optimize_decision(decision)
            if decision.trade_plan_quality is None
            else decision
            for decision in reviewed
        )
        qualities = tuple(
            decision.trade_plan_quality
            for decision in optimized
            if decision.trade_plan_quality is not None
        )
        scores = tuple(quality.trade_plan_quality_score for quality in qualities)
        weaknesses = Counter(
            weakness for quality in qualities for weakness in quality.weaknesses
        )
        return TradePlanAuditReport(
            accepted_opportunities_reviewed=len(reviewed),
            optimized_plans=sum(
                1
                for quality in qualities
                if quality.final_action is FinalDecisionAction.ACCEPT
            ),
            rejected_due_to_weak_trade_plan=sum(
                1
                for quality in qualities
                if quality.final_action is FinalDecisionAction.REJECT
            ),
            average_trade_plan_quality_score=None
            if not scores
            else (sum(scores, Decimal("0")) / Decimal(len(scores))).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            stop_quality_distribution=MappingProxyType(
                dict(Counter(quality.stop_quality.value for quality in qualities))
            ),
            target_quality_distribution=MappingProxyType(
                dict(Counter(quality.target_quality.value for quality in qualities))
            ),
            selected_exit_strategy_distribution=MappingProxyType(
                dict(
                    Counter(
                        quality.final_selected_plan.selected_exit_strategy.value
                        for quality in qualities
                        if quality.final_selected_plan is not None
                    )
                )
            ),
            common_trade_plan_weaknesses=tuple(weaknesses.most_common(5)),
        )

    def _stop_candidate(
        self,
        candidate: InstitutionalCandidate,
        *,
        name: str,
        level: Decimal | None,
    ) -> StopCandidate:
        entry = candidate.entry
        if entry is None or level is None or level >= entry:
            return StopCandidate(
                name=name,
                level=level,
                risk_percent=None,
                atr_multiple=None,
                reward_risk=None,
                quality=StopQuality.INVALID,
                accepted=False,
                explanation="Stop unavailable or not below entry.",
            )
        risk = ((entry - level) / entry * Decimal("100")).quantize(Decimal("0.01"))
        atr_multiple = (
            None
            if candidate.atr is None or candidate.atr <= Decimal("0")
            else ((entry - level) / candidate.atr).quantize(Decimal("0.01"))
        )
        reward_risk = _reward_risk(entry=entry, stop=level, target=candidate.target_1)
        quality = _stop_quality(risk)
        accepted = quality in {StopQuality.GOOD, StopQuality.ACCEPTABLE}
        return StopCandidate(
            name=name,
            level=level,
            risk_percent=risk,
            atr_multiple=atr_multiple,
            reward_risk=reward_risk,
            quality=quality,
            accepted=accepted,
            explanation=_stop_explanation(quality, risk),
        )

    def _target_candidate(
        self,
        candidate: InstitutionalCandidate,
        *,
        name: str,
        targets: tuple[Decimal, ...],
    ) -> TargetCandidate:
        entry = candidate.entry
        stop = candidate.stop
        valid_targets = tuple(
            target for target in targets if entry is not None and target > entry
        )
        if entry is None or stop is None or not valid_targets:
            return TargetCandidate(
                name=name,
                targets=valid_targets,
                reward_risk=None,
                atr_multiple=None,
                quality=TargetQuality.INVALID,
                accepted=False,
                explanation="Target unavailable or not above entry.",
            )
        reward_risk = _reward_risk(entry=entry, stop=stop, target=valid_targets[-1])
        atr_multiple = (
            None
            if candidate.atr is None or candidate.atr <= Decimal("0")
            else ((valid_targets[-1] - entry) / candidate.atr).quantize(Decimal("0.01"))
        )
        quality = _target_quality(reward_risk, atr_multiple)
        return TargetCandidate(
            name=name,
            targets=valid_targets,
            reward_risk=reward_risk,
            atr_multiple=atr_multiple,
            quality=quality,
            accepted=quality in {TargetQuality.GOOD, TargetQuality.ACCEPTABLE},
            explanation=_target_explanation(quality),
        )

    def _optimized_plan(
        self,
        *,
        candidate: InstitutionalCandidate,
        selected_stop: StopCandidate | None,
        selected_target: TargetCandidate | None,
        selected_exit: ExitStrategyAssessment,
    ) -> OptimizedTradePlan | None:
        if (
            candidate.entry is None
            or selected_stop is None
            or selected_stop.level is None
            or selected_target is None
            or selected_target.reward_risk is None
        ):
            return None
        reward_risk = _reward_risk(
            entry=candidate.entry,
            stop=selected_stop.level,
            target=selected_target.targets[-1],
        )
        if reward_risk is None:
            return None
        partial = (
            PartialProfitPlan(
                target_1_exit_percent=Decimal("50"),
                move_stop_to_breakeven=True,
                runner_targets=selected_target.targets[1:],
                trailing_stop_after_target_1=True,
                explanation=(
                    "Exit 50% at Target 1, move stop to breakeven, "
                    "trail the runner after Target 1."
                ),
            )
            if selected_exit.strategy_type
            in {
                ExitStrategyType.PARTIAL_PROFIT_RUNNER,
                ExitStrategyType.TRAILING_AFTER_TARGET_1,
            }
            else None
        )
        return OptimizedTradePlan(
            entry=candidate.entry,
            selected_stop=selected_stop.level,
            selected_targets=selected_target.targets,
            selected_exit_strategy=selected_exit.strategy_type,
            reward_risk=reward_risk,
            partial_profit_plan=partial,
            trailing_stop_rule="Trail below highest close after Target 1."
            if partial is not None
            else None,
            explanation=(
                f"Selected {selected_stop.name} and {selected_target.name} "
                f"using {selected_exit.strategy_type.value}."
            ),
        )

    def _quality_score(
        self,
        *,
        candidate: InstitutionalCandidate,
        stop: StopCandidate | None,
        target: TargetCandidate | None,
        exit_strategy: ExitStrategyAssessment,
    ) -> Decimal:
        if stop is None or target is None:
            return Decimal("0.00")
        evidence = {
            "strong": Decimal("100"),
            "moderate": Decimal("80"),
            "weak": Decimal("50"),
            "insufficient": Decimal("20"),
        }.get(candidate.evidence_strength or "insufficient", Decimal("20"))
        reward = min(
            (target.reward_risk or Decimal("0")) / Decimal("4") * Decimal("100"),
            Decimal("100"),
        )
        expected = (
            Decimal("35")
            if exit_strategy.expected_r is None
            else min(
                max(
                    Decimal("50") + exit_strategy.expected_r * Decimal("15"),
                    Decimal("0"),
                ),
                Decimal("100"),
            )
        )
        holding = (
            Decimal("80")
            if exit_strategy.average_holding_period is not None
            else Decimal("55")
        )
        score = (
            _stop_quality_score(stop.quality) * Decimal("0.20")
            + _target_quality_score(target.quality) * Decimal("0.20")
            + expected * Decimal("0.18")
            + reward * Decimal("0.16")
            + evidence * Decimal("0.10")
            + candidate.capacity.capacity_score * Decimal("0.08")
            + holding * Decimal("0.08")
            - exit_strategy.uncertainty_penalty
        )
        return max(Decimal("0"), min(score, Decimal("100"))).quantize(Decimal("0.01"))

    def _weaknesses(
        self,
        *,
        candidate: InstitutionalCandidate,
        selected_stop: StopCandidate | None,
        selected_target: TargetCandidate | None,
        selected_exit: ExitStrategyAssessment,
    ) -> tuple[str, ...]:
        weaknesses: list[str] = []
        if selected_stop is None:
            weaknesses.append("No acceptable stop candidate.")
        if selected_target is None:
            weaknesses.append("No realistic target candidate.")
        if candidate.evidence_strength in {"weak", "insufficient", None}:
            weaknesses.append("Evidence strength limits trade-plan confidence.")
        if selected_exit.uncertainty_penalty >= Decimal("10"):
            weaknesses.append("Exit strategy has high uncertainty penalty.")
        if candidate.capacity.capacity_score < Decimal("60"):
            weaknesses.append("Capacity quality constrains execution.")
        return tuple(weaknesses)


def _offset(entry: Decimal | None, multiplier: Decimal) -> Decimal | None:
    if entry is None:
        return None
    return (entry * multiplier).quantize(Decimal("0.01"))


def _atr_stop(entry: Decimal | None, atr: Decimal | None) -> Decimal | None:
    if entry is None or atr is None:
        return None
    return (entry - (atr * Decimal("1.8"))).quantize(Decimal("0.01"))


def _reward_risk(
    *,
    entry: Decimal,
    stop: Decimal,
    target: Decimal | None,
) -> Decimal | None:
    if target is None:
        return None
    risk = entry - stop
    if risk <= Decimal("0"):
        return None
    return ((target - entry) / risk).quantize(Decimal("0.01"))


def _stop_quality(risk: Decimal) -> StopQuality:
    if risk < Decimal("2") or risk > Decimal("12"):
        return StopQuality.INVALID
    if risk < Decimal("3") or risk > Decimal("9"):
        return StopQuality.WEAK
    if risk <= Decimal("7"):
        return StopQuality.GOOD
    return StopQuality.ACCEPTABLE


def _target_quality(
    reward_risk: Decimal | None,
    atr_multiple: Decimal | None,
) -> TargetQuality:
    if reward_risk is None or reward_risk < Decimal("2"):
        return TargetQuality.INVALID
    if reward_risk > Decimal("5") or (
        atr_multiple is not None and atr_multiple > Decimal("8")
    ):
        return TargetQuality.WEAK
    if reward_risk >= Decimal("3"):
        return TargetQuality.GOOD
    return TargetQuality.ACCEPTABLE


def _stop_explanation(quality: StopQuality, risk: Decimal) -> str:
    if quality is StopQuality.INVALID:
        return f"Rejected because stop risk is {risk}%."
    if quality is StopQuality.WEAK:
        return f"Rejected because stop risk is marginal at {risk}%."
    return f"Accepted because stop risk is {risk}%."


def _target_explanation(quality: TargetQuality) -> str:
    if quality is TargetQuality.INVALID:
        return "Rejected because target reward/risk is below 2R."
    if quality is TargetQuality.WEAK:
        return "Rejected because target appears too optimistic."
    return "Accepted because target is realistic for the trade plan."


def _strategy(
    strategy_type: ExitStrategyType,
    expected_r: Decimal | None,
    win_rate: Decimal | None,
    downside: Decimal | None,
    samples: int | None,
    uncertainty: Decimal,
    explanation: str,
) -> ExitStrategyAssessment:
    return ExitStrategyAssessment(
        strategy_type=strategy_type,
        expected_r=expected_r,
        estimated_win_rate=win_rate,
        downside_exposure=downside,
        average_holding_period=Decimal("10") if samples is not None else None,
        evidence_sample_count=samples,
        uncertainty_penalty=uncertainty,
        selected=False,
        explanation=explanation,
    )


def _mark_selected(
    strategy: ExitStrategyAssessment,
    selected: ExitStrategyType,
) -> ExitStrategyAssessment:
    return ExitStrategyAssessment(
        strategy_type=strategy.strategy_type,
        expected_r=strategy.expected_r,
        estimated_win_rate=strategy.estimated_win_rate,
        downside_exposure=strategy.downside_exposure,
        average_holding_period=strategy.average_holding_period,
        evidence_sample_count=strategy.evidence_sample_count,
        uncertainty_penalty=strategy.uncertainty_penalty,
        selected=strategy.strategy_type is selected,
        explanation=strategy.explanation,
    )


def _plus(value: Decimal | None, extra: Decimal) -> Decimal | None:
    if value is None:
        return None
    return (value + extra).quantize(Decimal("0.01"))


def _minus(value: Decimal | None, extra: Decimal) -> Decimal | None:
    if value is None:
        return None
    return (value - extra).quantize(Decimal("0.01"))


def _stop_quality_score(value: StopQuality) -> Decimal:
    return {
        StopQuality.GOOD: Decimal("95"),
        StopQuality.ACCEPTABLE: Decimal("75"),
        StopQuality.WEAK: Decimal("40"),
        StopQuality.INVALID: Decimal("0"),
    }[value]


def _target_quality_score(value: TargetQuality) -> Decimal:
    return {
        TargetQuality.GOOD: Decimal("95"),
        TargetQuality.ACCEPTABLE: Decimal("75"),
        TargetQuality.WEAK: Decimal("40"),
        TargetQuality.INVALID: Decimal("0"),
    }[value]


def _stop_structure_rank(name: str) -> int:
    if name in {"20-DMA stop", "support stop", "swing-low stop"}:
        return 2
    if name == "ATR stop":
        return 1
    return 0


def _confidence_from_quality(value: StopQuality | TargetQuality) -> Decimal:
    if value.value == "good":
        return Decimal("0.90")
    if value.value == "acceptable":
        return Decimal("0.70")
    if value.value == "weak":
        return Decimal("0.40")
    return Decimal("0.00")


__all__ = ["TradePlanOptimizationEngine"]
