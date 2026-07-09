from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from alpha.recommendation_intelligence.models import (
    AllocationAdjustment,
    CandidateComparison,
    ExpectedValueAssessment,
    OpportunityCostAssessment,
    PortfolioContext,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationReport,
    RecommendationScore,
    RecommendationScoreBreakdown,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


class ExpectedValueEngine:
    """Score expected value using deterministic return/drawdown evidence."""

    def assess(self, candidate: RecommendationCandidate) -> ExpectedValueAssessment:
        drawdown = candidate.expected_drawdown
        if drawdown <= _ZERO:
            reward_to_risk = candidate.expected_return
        else:
            reward_to_risk = candidate.expected_return / drawdown

        return_score = _positive_ratio(candidate.expected_return / Decimal("0.12"))
        reward_quality_score = _positive_ratio(reward_to_risk / Decimal("3"))
        drawdown_quality_score = _drawdown_quality(candidate.expected_drawdown)

        score = _bounded_ratio(
            return_score * Decimal("0.35")
            + reward_quality_score * Decimal("0.35")
            + candidate.probability_score * Decimal("0.20")
            + drawdown_quality_score * Decimal("0.10")
        )

        return ExpectedValueAssessment(
            symbol=candidate.symbol,
            expected_return=candidate.expected_return,
            expected_drawdown=candidate.expected_drawdown,
            reward_to_risk=_quantize(reward_to_risk),
            expected_holding_period_days=candidate.expected_holding_period_days,
            score=score,
            reasons=(
                f"expected return: {_as_percent(candidate.expected_return)}",
                f"expected drawdown: {_as_percent(candidate.expected_drawdown)}",
                f"reward to risk: {_quantize(reward_to_risk)}",
            ),
        )


class OpportunityCostEngine:
    """Rank candidates against one another before allocating capital."""

    def assess(
        self,
        *,
        target: RecommendationCandidate,
        candidates: Iterable[RecommendationCandidate],
    ) -> OpportunityCostAssessment:
        candidate_tuple = tuple(candidates)
        if len(candidate_tuple) == 0:
            raise ValueError("opportunity cost requires at least one candidate")

        target_symbol = target.symbol
        scored = tuple(
            sorted(
                (
                    CandidateComparison(
                        symbol=candidate.symbol,
                        score=self._ranking_score(candidate),
                        expected_return=candidate.expected_return,
                        expected_drawdown=candidate.expected_drawdown,
                        rank=1,
                    )
                    for candidate in candidate_tuple
                ),
                key=lambda comparison: (-comparison.score, comparison.symbol),
            )
        )

        ranked = tuple(
            CandidateComparison(
                symbol=comparison.symbol,
                score=comparison.score,
                expected_return=comparison.expected_return,
                expected_drawdown=comparison.expected_drawdown,
                rank=index,
            )
            for index, comparison in enumerate(scored, start=1)
        )

        target_match = next(
            (comparison for comparison in ranked if comparison.symbol == target_symbol),
            None,
        )
        if target_match is None:
            raise ValueError("target candidate must be present in candidates")

        better_candidates = tuple(
            comparison for comparison in ranked if comparison.rank < target_match.rank
        )
        percentile = Decimal(len(ranked) - target_match.rank + 1) / Decimal(len(ranked))
        opportunity_points = (percentile - Decimal("0.50")) * Decimal("10")

        return OpportunityCostAssessment(
            symbol=target_symbol,
            rank=target_match.rank,
            candidate_count=len(ranked),
            percentile=_quantize(percentile),
            opportunity_cost_points=_quantize(opportunity_points),
            better_candidates=better_candidates,
            reasons=(
                f"rank: {target_match.rank} of {len(ranked)}",
                f"opportunity percentile: {_as_percent(percentile)}",
                f"better candidates: {len(better_candidates)}",
            ),
        )

    def _ranking_score(self, candidate: RecommendationCandidate) -> Decimal:
        return _bounded_ratio(
            candidate.strategy_score * Decimal("0.25")
            + candidate.probability_score * Decimal("0.25")
            + candidate.market_intelligence_score * Decimal("0.25")
            + candidate.liquidity_score * Decimal("0.15")
            + candidate.risk_score * Decimal("0.10")
        )


class PortfolioAwarenessEngine:
    """Apply portfolio concentration and duplication adjustments."""

    def assess(
        self,
        *,
        candidate: RecommendationCandidate,
        context: PortfolioContext | None = None,
    ) -> AllocationAdjustment:
        portfolio = context or PortfolioContext()
        reasons: list[str] = []
        adjustment_points = _ZERO

        base_allocation = self._base_allocation(candidate)
        adjusted_allocation = min(
            base_allocation,
            portfolio.max_single_position_percent,
        )

        if candidate.symbol in portfolio.existing_symbols:
            adjusted_allocation *= Decimal("0.65")
            adjustment_points -= Decimal("3")
            reasons.append("existing position already present")

        sector = portfolio.symbol_sector.get(candidate.symbol)
        if sector is not None:
            exposure = portfolio.sector_exposure.get(sector, _ZERO)
            if exposure >= portfolio.max_sector_exposure_percent:
                adjusted_allocation *= Decimal("0.50")
                adjustment_points -= Decimal("5")
                reasons.append(f"sector exposure already high: {sector}")
            else:
                reasons.append(f"sector exposure acceptable: {sector}")
        else:
            reasons.append("sector exposure unavailable")

        if not reasons:
            reasons.append("no portfolio constraints applied")

        return AllocationAdjustment(
            base_allocation_percent=_quantize(base_allocation),
            adjusted_allocation_percent=_quantize(adjusted_allocation),
            adjustment_points=_quantize(adjustment_points),
            reasons=tuple(reasons),
        )

    def _base_allocation(self, candidate: RecommendationCandidate) -> Decimal:
        conviction = (
            candidate.strategy_score
            + candidate.probability_score
            + candidate.market_intelligence_score
            + candidate.liquidity_score
            + candidate.risk_score
        ) / Decimal("5")
        return Decimal("2") + conviction * Decimal("8")


class RecommendationScoringEngine:
    """Combine deterministic score components into one semantic score.

    EPIC-B3 rule:
    The score is the source of truth. Action and decision are both derived from
    the final score so the report never says BUY while the score says AVOID.
    """

    def score(
        self,
        *,
        candidate: RecommendationCandidate,
        opportunity_cost: OpportunityCostAssessment,
        allocation: AllocationAdjustment,
    ) -> RecommendationScore:
        breakdown = RecommendationScoreBreakdown(
            strategy_points=_quantize(candidate.strategy_score * Decimal("28")),
            probability_points=_quantize(candidate.probability_score * Decimal("24")),
            market_intelligence_points=_quantize(
                candidate.market_intelligence_score * Decimal("22")
            ),
            liquidity_points=_quantize(candidate.liquidity_score * Decimal("14")),
            risk_points=_quantize(candidate.risk_score * Decimal("8")),
            portfolio_adjustment_points=allocation.adjustment_points,
            opportunity_cost_points=opportunity_cost.opportunity_cost_points,
        )
        raw_score = max(_ZERO, min(_HUNDRED, breakdown.total_points))
        score = raw_score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        return RecommendationScore(
            symbol=candidate.symbol,
            score=score,
            decision=self._decision(score),
            breakdown=breakdown,
        )

    def action_for_score(self, score: Decimal) -> RecommendationAction:
        """Return the outward recommendation action for a final score."""

        normalized_score = Decimal(str(score))
        if normalized_score >= Decimal("80"):
            return RecommendationAction.BUY
        if normalized_score >= Decimal("65"):
            return RecommendationAction.ACCUMULATE
        if normalized_score >= Decimal("50"):
            return RecommendationAction.HOLD
        if normalized_score >= Decimal("40"):
            return RecommendationAction.REDUCE
        return RecommendationAction.AVOID

    def _decision(self, score: Decimal) -> RecommendationDecision:
        if score >= Decimal("90"):
            return RecommendationDecision.STRONG_BUY
        if score >= Decimal("80"):
            return RecommendationDecision.BUY
        if score >= Decimal("65"):
            return RecommendationDecision.WATCHLIST
        if score >= Decimal("50"):
            return RecommendationDecision.HOLD
        return RecommendationDecision.AVOID


class RecommendationEngine:
    """Build sorted, explainable recommendation reports."""

    def __init__(
        self,
        *,
        expected_value_engine: ExpectedValueEngine | None = None,
        opportunity_cost_engine: OpportunityCostEngine | None = None,
        portfolio_engine: PortfolioAwarenessEngine | None = None,
        scoring_engine: RecommendationScoringEngine | None = None,
    ) -> None:
        self._expected_value_engine = expected_value_engine or ExpectedValueEngine()
        self._opportunity_cost_engine = (
            opportunity_cost_engine or OpportunityCostEngine()
        )
        self._portfolio_engine = portfolio_engine or PortfolioAwarenessEngine()
        self._scoring_engine = scoring_engine or RecommendationScoringEngine()

    def build(
        self,
        candidates: Iterable[RecommendationCandidate],
        *,
        portfolio: PortfolioContext | None = None,
    ) -> tuple[RecommendationReport, ...]:
        candidate_tuple = tuple(candidates)
        if len(candidate_tuple) == 0:
            return ()

        reports = tuple(
            self._build_one(
                candidate=candidate,
                candidates=candidate_tuple,
                portfolio=portfolio,
            )
            for candidate in candidate_tuple
        )

        return tuple(
            sorted(
                reports,
                key=lambda report: (
                    -report.score,
                    -report.expected_value.score,
                    report.symbol,
                ),
            )
        )

    def _build_one(
        self,
        *,
        candidate: RecommendationCandidate,
        candidates: tuple[RecommendationCandidate, ...],
        portfolio: PortfolioContext | None,
    ) -> RecommendationReport:
        expected_value = self._expected_value_engine.assess(candidate)
        opportunity_cost = self._opportunity_cost_engine.assess(
            target=candidate,
            candidates=candidates,
        )
        allocation = self._portfolio_engine.assess(
            candidate=candidate,
            context=portfolio,
        )
        score = self._scoring_engine.score(
            candidate=candidate,
            opportunity_cost=opportunity_cost,
            allocation=allocation,
        )
        action = self._scoring_engine.action_for_score(score.score)

        return RecommendationReport(
            symbol=candidate.symbol,
            observed_on=candidate.observed_on,
            action=action,
            decision=score.decision,
            score=score.score,
            score_breakdown=score.breakdown,
            expected_value=expected_value,
            opportunity_cost=opportunity_cost,
            allocation=allocation,
            supporting_evidence=candidate.evidence,
            opposing_evidence=candidate.risks,
            explanation=self._explanation(
                candidate=candidate,
                action=action,
                score=score,
                expected_value=expected_value,
                opportunity_cost=opportunity_cost,
                allocation=allocation,
            ),
            metadata=candidate.metadata,
        )

    def _explanation(
        self,
        *,
        candidate: RecommendationCandidate,
        action: RecommendationAction,
        score: RecommendationScore,
        expected_value: ExpectedValueAssessment,
        opportunity_cost: OpportunityCostAssessment,
        allocation: AllocationAdjustment,
    ) -> tuple[str, ...]:
        lines = [
            f"{candidate.symbol}: {score.decision.value}",
            f"Recommendation Score: {score.score}/100",
            f"Action: {action.value}",
            "Why this ranks here:",
            f"- Strategy score: {_as_percent(candidate.strategy_score)}",
            f"- Probability score: {_as_percent(candidate.probability_score)}",
            f"- Market intelligence score: "
            f"{_as_percent(candidate.market_intelligence_score)}",
            f"- Liquidity score: {_as_percent(candidate.liquidity_score)}",
            f"- Risk quality score: {_as_percent(candidate.risk_score)}",
            f"- Expected value: {_as_percent(expected_value.expected_return)} return, "
            f"{_as_percent(expected_value.expected_drawdown)} drawdown",
            f"- Opportunity cost: rank {opportunity_cost.rank} of "
            f"{opportunity_cost.candidate_count}",
            f"- Suggested allocation: {allocation.adjusted_allocation_percent}%",
        ]

        lines.extend(
            f"Support: {evidence.label} - {evidence.rationale}"
            for evidence in candidate.evidence
        )
        lines.extend(
            f"Risk: {risk.label} - {risk.rationale}" for risk in candidate.risks
        )

        return tuple(lines)


def _drawdown_quality(drawdown: Decimal) -> Decimal:
    normalized_drawdown = Decimal(str(drawdown))
    if normalized_drawdown <= _ZERO:
        return _ONE
    if normalized_drawdown >= Decimal("0.15"):
        return _ZERO

    return _bounded_ratio(_ONE - normalized_drawdown / Decimal("0.15"))


def _positive_ratio(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized <= _ZERO:
        return _ZERO
    if normalized >= _ONE:
        return _ONE
    return _quantize(normalized)


def _bounded_ratio(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO:
        return _ZERO
    if normalized > _ONE:
        return _ONE
    return _quantize(normalized)


def _quantize(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def _as_percent(value: Decimal) -> str:
    return f"{(Decimal(str(value)) * _HUNDRED).quantize(_TWO_PLACES)}%"


__all__ = [
    "ExpectedValueEngine",
    "OpportunityCostEngine",
    "PortfolioAwarenessEngine",
    "RecommendationEngine",
    "RecommendationScoringEngine",
]
