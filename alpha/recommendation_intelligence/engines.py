from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal

from alpha.recommendation_intelligence.models import (
    AllocationAdjustment,
    CandidateComparison,
    CandlePatternAssessment,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceSignal,
    ExpectedValueAssessment,
    HistoricalExpectancy,
    OpportunityCostAssessment,
    PortfolioContext,
    PriceEvidence,
    PriceVolumeAssessment,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationReport,
    RecommendationScore,
    RecommendationScoreBreakdown,
    RecommendationTradePlan,
    SetupQualityAssessment,
    VolumeEvidence,
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
                key=lambda comparison: (
                    -comparison.score,
                    comparison.symbol,
                ),
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
        opportunity_points = (percentile - Decimal("0.50")) * Decimal("30")

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
            candidate.strategy_score * Decimal("0.22")
            + candidate.probability_score * Decimal("0.22")
            + candidate.market_intelligence_score * Decimal("0.22")
            + candidate.liquidity_score * Decimal("0.13")
            + candidate.risk_score * Decimal("0.09")
            + candidate.retracement_score * Decimal("0.12")
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


class PriceVolumeSignalEngine:
    """Evaluate price and volume as the primary technical source of truth."""

    def assess(self, candidate: RecommendationCandidate) -> PriceVolumeAssessment:
        price_evidence = self._price_evidence(candidate)
        volume_evidence = self._volume_evidence(candidate)
        override_reasons = self._override_reasons(
            candidate,
            price_evidence,
            volume_evidence,
        )
        supports_sell = (
            price_evidence.breakout_state == "BREAKDOWN"
            and volume_evidence.selloff_volume_penalty >= Decimal("0.70")
        ) or candidate.lower_highs_lower_lows
        supports_buy = (
            price_evidence.price_score >= Decimal("0.60")
            and volume_evidence.volume_score >= Decimal("0.55")
            and not override_reasons
        )
        return PriceVolumeAssessment(
            price_evidence=price_evidence,
            volume_evidence=volume_evidence,
            supports_buy=supports_buy,
            supports_sell=supports_sell,
            override_reasons=override_reasons,
        )

    def _price_evidence(self, candidate: RecommendationCandidate) -> PriceEvidence:
        trend_score = candidate.price_trend_score or self._price_trend_score(candidate)
        momentum_score = candidate.price_momentum_score or self._price_momentum_score(
            candidate,
        )
        structure_score = candidate.price_structure_score or self._structure_score(
            candidate,
        )
        breakout_score = candidate.price_breakout_score or self._breakout_score(
            candidate,
        )
        breakdown_score = candidate.price_breakdown_score or self._breakdown_score(
            candidate,
        )
        close_strength = candidate.close_location_score or self._close_strength(
            candidate,
        )
        volatility_score = (
            candidate.volatility_expansion_score or self._volatility_score(candidate)
        )
        support_score = self._support_resistance_score(candidate)
        retracement_score = self._price_volume_retracement_score(candidate)
        price_score = _bounded_ratio(
            structure_score * Decimal("0.28")
            + trend_score * Decimal("0.20")
            + momentum_score * Decimal("0.15")
            + max(breakout_score, _ONE - breakdown_score) * Decimal("0.12")
            + support_score * Decimal("0.10")
            + close_strength * Decimal("0.08")
            + volatility_score * Decimal("0.07")
        )

        return PriceEvidence(
            trend_state=self._trend_state(trend_score),
            structure_state=self._structure_state(candidate, structure_score),
            breakout_state=self._breakout_state(
                candidate,
                breakout_score,
                breakdown_score,
            ),
            retracement_state=self._retracement_state(candidate, retracement_score),
            support_resistance_state=self._support_resistance_state(
                candidate,
                support_score,
            ),
            close_strength=close_strength,
            volatility_state=self._volatility_state(volatility_score),
            price_score=price_score,
        )

    def _volume_evidence(self, candidate: RecommendationCandidate) -> VolumeEvidence:
        volume_vs_average = self._volume_vs_average(candidate)
        volume_expansion = candidate.volume_expansion_score or _bounded_ratio(
            volume_vs_average / Decimal("2")
        )
        volume_dry_up = candidate.volume_dry_up_score or _bounded_ratio(
            _ONE - min(volume_vs_average, _ONE)
        )
        accumulation = candidate.accumulation_score or self._accumulation_score(
            candidate,
            volume_vs_average,
        )
        distribution = candidate.distribution_score or self._distribution_score(
            candidate,
            volume_vs_average,
        )
        breakout_confirmation = (
            candidate.breakout_volume_confirmation
            or self._breakout_volume_confirmation(candidate, volume_vs_average)
        )
        selloff_penalty = candidate.selloff_volume_penalty or self._selloff_penalty(
            candidate,
            volume_vs_average,
        )
        volume_score = _bounded_ratio(
            volume_expansion * Decimal("0.20")
            + volume_dry_up * Decimal("0.12")
            + accumulation * Decimal("0.24")
            + (_ONE - distribution) * Decimal("0.16")
            + breakout_confirmation * Decimal("0.20")
            + (_ONE - selloff_penalty) * Decimal("0.08")
        )
        if _metadata_decimal(candidate, "volume") is None:
            volume_score = max(
                volume_score,
                candidate.volume_confirmation_score or candidate.liquidity_score,
            )
        return VolumeEvidence(
            volume_vs_average=volume_vs_average,
            volume_expansion_score=volume_expansion,
            volume_dry_up_score=volume_dry_up,
            accumulation_score=accumulation,
            distribution_score=distribution,
            breakout_volume_confirmation=breakout_confirmation,
            selloff_volume_penalty=selloff_penalty,
            volume_score=volume_score,
        )

    def _override_reasons(
        self,
        candidate: RecommendationCandidate,
        price_evidence: PriceEvidence,
        volume_evidence: VolumeEvidence,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        high_volume = volume_evidence.volume_vs_average >= Decimal("1.50")
        weak_volume = volume_evidence.breakout_volume_confirmation < Decimal(
            "0.45"
        ) or volume_evidence.volume_score < Decimal("0.45")
        if (
            candidate.dma_50 is not None
            and _is_below(
                candidate.current_price,
                candidate.dma_50,
            )
            and high_volume
        ):
            reasons.append("No BUY: price broke below 50-DMA on high volume.")
        if candidate.breakout_attempt and weak_volume:
            reasons.append("No BUY: breakout occurred on weak volume.")
        if candidate.lower_highs_lower_lows:
            reasons.append("No BUY: price is making lower highs and lower lows.")
        if (
            price_evidence.breakout_state == "BREAKDOWN"
            and volume_evidence.selloff_volume_penalty >= Decimal("0.70")
        ):
            reasons.append("SELL/AVOID: breakdown below key support on heavy volume.")
        if (
            price_evidence.trend_state in {"UPTREND", "STRONG_UPTREND"}
            and volume_evidence.volume_score < Decimal("0.50")
            and candidate.current_price is not None
            and candidate.previous_close is not None
        ):
            reasons.append("Confidence reduced: price rises while volume declines.")
        return tuple(reasons)

    def _price_trend_score(self, candidate: RecommendationCandidate) -> Decimal:
        current_price = candidate.current_price
        levels = tuple(
            level
            for level in (
                candidate.dma_20,
                candidate.ema_20,
                candidate.dma_50,
                candidate.ema_50,
                candidate.dma_200,
                candidate.ema_200,
            )
            if level is not None
        )
        if current_price is None or not levels:
            return candidate.trend_structure_score or candidate.strategy_score
        above_count = sum(1 for level in levels if current_price >= level)
        return _bounded_ratio(Decimal(above_count) / Decimal(len(levels)))

    def _price_momentum_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.current_price is None or candidate.previous_close is None:
            return candidate.momentum_confirmation_score or candidate.strategy_score
        change = (candidate.current_price - candidate.previous_close) / max(
            candidate.previous_close,
            Decimal("0.01"),
        )
        return _bounded_ratio(Decimal("0.50") + (change * Decimal("5")))

    def _structure_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.higher_highs_higher_lows:
            return Decimal("0.90")
        if candidate.lower_highs_lower_lows:
            return Decimal("0.10")
        return candidate.trend_structure_score or candidate.strategy_score

    def _breakout_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.price_breakout_score is not None:
            return candidate.price_breakout_score
        if candidate.resistance_level is None or candidate.current_price is None:
            return candidate.breakout_setup_score or candidate.strategy_score
        if candidate.current_price > candidate.resistance_level:
            return Decimal("0.90")
        if candidate.current_price == candidate.resistance_level:
            return Decimal("0.65")
        return Decimal("0.35")

    def _breakdown_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.price_breakdown_score is not None:
            return candidate.price_breakdown_score
        if candidate.support_level is None or candidate.current_price is None:
            return Decimal("0.20")
        if candidate.current_price < candidate.support_level:
            return Decimal("0.90")
        return Decimal("0.20")

    def _close_strength(self, candidate: RecommendationCandidate) -> Decimal:
        if (
            candidate.high_price is None
            or candidate.low_price is None
            or candidate.current_price is None
        ):
            return Decimal("0.50")
        candle_range = candidate.high_price - candidate.low_price
        if candle_range <= _ZERO:
            return Decimal("0.50")
        return _bounded_ratio(
            (candidate.current_price - candidate.low_price) / candle_range
        )

    def _volatility_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.volatility_expansion_score is not None:
            return candidate.volatility_expansion_score
        if (
            candidate.high_price is None
            or candidate.low_price is None
            or candidate.atr is None
            or candidate.atr <= _ZERO
        ):
            return candidate.risk_score
        range_to_atr = (candidate.high_price - candidate.low_price) / candidate.atr
        if range_to_atr > Decimal("2.50"):
            return Decimal("0.25")
        if range_to_atr < Decimal("0.80"):
            return Decimal("0.75")
        return Decimal("0.60")

    def _support_resistance_score(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.current_price is None:
            return Decimal("0.50")
        if (
            candidate.support_level is not None
            and candidate.current_price < candidate.support_level
        ):
            return Decimal("0.15")
        if (
            candidate.resistance_level is not None
            and candidate.current_price > candidate.resistance_level
        ):
            return Decimal("0.85")
        return Decimal("0.60")

    def _price_volume_retracement_score(
        self,
        candidate: RecommendationCandidate,
    ) -> Decimal:
        volume_dry_up = candidate.volume_dry_up_score or Decimal("0.50")
        bounce_volume = candidate.breakout_volume_confirmation or Decimal("0.50")
        support_hold = self._support_resistance_score(candidate)
        base = candidate.retracement_score
        if candidate.lower_highs_lower_lows:
            return min(base, Decimal("0.30"))
        if (
            candidate.selloff_volume_penalty
            and candidate.selloff_volume_penalty >= Decimal("0.70")
        ):
            return min(base, Decimal("0.35"))
        return _bounded_ratio(
            base * Decimal("0.40")
            + volume_dry_up * Decimal("0.25")
            + bounce_volume * Decimal("0.20")
            + support_hold * Decimal("0.15")
        )

    def _volume_vs_average(self, candidate: RecommendationCandidate) -> Decimal:
        volume = _metadata_decimal(candidate, "volume")
        average_volume = _metadata_decimal(candidate, "average_volume")
        if volume is None or average_volume is None or average_volume <= _ZERO:
            return _ONE
        return volume / average_volume

    def _accumulation_score(
        self,
        candidate: RecommendationCandidate,
        volume_vs_average: Decimal,
    ) -> Decimal:
        close_strength = self._close_strength(candidate)
        if close_strength >= Decimal("0.70") and volume_vs_average >= Decimal("1.20"):
            return Decimal("0.85")
        if close_strength >= Decimal("0.55"):
            return Decimal("0.60")
        return Decimal("0.35")

    def _distribution_score(
        self,
        candidate: RecommendationCandidate,
        volume_vs_average: Decimal,
    ) -> Decimal:
        close_strength = self._close_strength(candidate)
        if close_strength <= Decimal("0.30") and volume_vs_average >= Decimal("1.20"):
            return Decimal("0.85")
        if close_strength <= Decimal("0.45"):
            return Decimal("0.55")
        return Decimal("0.25")

    def _breakout_volume_confirmation(
        self,
        candidate: RecommendationCandidate,
        volume_vs_average: Decimal,
    ) -> Decimal:
        if candidate.breakout_attempt or self._breakout_score(candidate) >= Decimal(
            "0.80"
        ):
            return _bounded_ratio(volume_vs_average / Decimal("1.50"))
        return candidate.volume_confirmation_score or candidate.liquidity_score

    def _selloff_penalty(
        self,
        candidate: RecommendationCandidate,
        volume_vs_average: Decimal,
    ) -> Decimal:
        if self._breakdown_score(candidate) >= Decimal(
            "0.80"
        ) and volume_vs_average >= Decimal("1.30"):
            return Decimal("0.90")
        if candidate.current_price is not None and candidate.previous_close is not None:
            if (
                candidate.current_price < candidate.previous_close
                and volume_vs_average >= Decimal("1.50")
            ):
                return Decimal("0.75")
        return Decimal("0.20")

    def _trend_state(self, score: Decimal) -> str:
        if score >= Decimal("0.80"):
            return "STRONG_UPTREND"
        if score >= Decimal("0.60"):
            return "UPTREND"
        if score <= Decimal("0.30"):
            return "DOWNTREND"
        return "SIDEWAYS"

    def _structure_state(
        self,
        candidate: RecommendationCandidate,
        score: Decimal,
    ) -> str:
        if candidate.higher_highs_higher_lows:
            return "HIGHER_HIGHS_HIGHER_LOWS"
        if candidate.lower_highs_lower_lows:
            return "LOWER_HIGHS_LOWER_LOWS"
        if score >= Decimal("0.60"):
            return "CONSTRUCTIVE"
        if score <= Decimal("0.40"):
            return "DETERIORATING"
        return "NEUTRAL"

    def _breakout_state(
        self,
        candidate: RecommendationCandidate,
        breakout_score: Decimal,
        breakdown_score: Decimal,
    ) -> str:
        if breakdown_score >= Decimal("0.80") or candidate.breakdown_attempt:
            return "BREAKDOWN"
        if breakout_score >= Decimal("0.80") or candidate.breakout_attempt:
            return "BREAKOUT"
        return "NONE"

    def _retracement_state(
        self,
        candidate: RecommendationCandidate,
        score: Decimal,
    ) -> str:
        if score >= Decimal("0.70"):
            return "HEALTHY"
        if score <= Decimal("0.40"):
            return "BAD"
        return "NEUTRAL"

    def _support_resistance_state(
        self,
        candidate: RecommendationCandidate,
        score: Decimal,
    ) -> str:
        if candidate.support_level is not None and _is_below(
            candidate.current_price,
            candidate.support_level,
        ):
            return "BELOW_SUPPORT"
        if (
            candidate.resistance_level is not None
            and candidate.current_price is not None
        ):
            if candidate.current_price > candidate.resistance_level:
                return "ABOVE_RESISTANCE"
        if score >= Decimal("0.60"):
            return "HOLDING_SUPPORT"
        return "NEUTRAL"

    def _volatility_state(self, score: Decimal) -> str:
        if score <= Decimal("0.35"):
            return "EXPANDING_RISK"
        if score >= Decimal("0.70"):
            return "CONTROLLED"
        return "NORMAL"


class CandlePatternEngine:
    """Detect context-aware candlestick confirmation from OHLCV behavior."""

    _WEIGHT = Decimal("0.08")

    def assess(
        self,
        *,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> CandlePatternAssessment:
        pattern = self._detect_pattern(candidate)
        base_score = self._base_score(pattern)
        score = self._context_score(candidate, price_volume, pattern, base_score)
        confirmation = self._confirmation(price_volume, pattern, score)
        entry_trigger = candidate.high_price
        stop_level = candidate.low_price
        invalidation_level = candidate.low_price
        if pattern == "NONE":
            entry_trigger = None
            stop_level = None
            invalidation_level = None

        explanation = (
            f"{pattern} detected. Candle {confirmation.lower()} price-volume; "
            f"high={entry_trigger}, low={stop_level}, "
            f"volume_confirmed={self._volume_confirmed(price_volume)}."
        )
        return CandlePatternAssessment(
            pattern=pattern,
            score=score,
            weight=self._WEIGHT,
            confirmation=confirmation,
            entry_trigger=entry_trigger,
            stop_level=stop_level,
            invalidation_level=invalidation_level,
            explanation=explanation,
            volume_confirmed=self._volume_confirmed(price_volume),
        )

    def _detect_pattern(self, candidate: RecommendationCandidate) -> str:
        if not self._has_current_candle(candidate):
            return "NONE"

        current_body = self._body(candidate.open_price, candidate.current_price)
        current_range = self._range(candidate.high_price, candidate.low_price)
        upper_wick = self._upper_wick(candidate)
        lower_wick = self._lower_wick(candidate)
        close_strength = self._close_strength(candidate)
        bullish = self._is_bullish(candidate.open_price, candidate.current_price)
        bearish = self._is_bearish(candidate.open_price, candidate.current_price)
        previous_bullish = self._is_bullish(
            candidate.previous_open_price,
            candidate.previous_close,
        )
        previous_bearish = self._is_bearish(
            candidate.previous_open_price,
            candidate.previous_close,
        )

        if self._is_morning_star(candidate):
            return "MORNING_STAR"
        if self._is_evening_star(candidate):
            return "EVENING_STAR"
        if (
            bullish
            and previous_bearish
            and candidate.open_price is not None
            and candidate.current_price is not None
            and candidate.previous_open_price is not None
            and candidate.previous_close is not None
            and candidate.open_price < candidate.previous_close
            and candidate.current_price > candidate.previous_open_price
        ):
            return "BULLISH_ENGULFING"
        if (
            bearish
            and previous_bullish
            and candidate.open_price is not None
            and candidate.current_price is not None
            and candidate.previous_open_price is not None
            and candidate.previous_close is not None
            and candidate.open_price > candidate.previous_close
            and candidate.current_price < candidate.previous_open_price
        ):
            return "BEARISH_ENGULFING"
        if current_range > _ZERO and current_body <= current_range * Decimal("0.10"):
            return "DOJI"
        if (
            candidate.previous_high_price is not None
            and candidate.previous_low_price is not None
        ):
            if (
                candidate.high_price is not None
                and candidate.low_price is not None
                and candidate.high_price < candidate.previous_high_price
                and candidate.low_price > candidate.previous_low_price
            ):
                return "INSIDE_BAR"
            if (
                candidate.high_price is not None
                and candidate.low_price is not None
                and candidate.high_price > candidate.previous_high_price
                and candidate.low_price < candidate.previous_low_price
            ):
                return "OUTSIDE_BAR"
        if current_body > _ZERO and lower_wick >= current_body * Decimal("2"):
            if upper_wick <= current_body:
                return "HAMMER"
            return "PIN_BAR_REJECTION"
        if current_body > _ZERO and upper_wick >= current_body * Decimal("2"):
            if lower_wick <= current_body:
                return "SHOOTING_STAR"
            return "PIN_BAR_REJECTION"
        if bullish and close_strength >= Decimal("0.80"):
            return "STRONG_BULLISH_CLOSE"
        if bearish and close_strength <= Decimal("0.20"):
            return "STRONG_BEARISH_CLOSE"
        return "NONE"

    def _context_score(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        pattern: str,
        base_score: Decimal,
    ) -> Decimal:
        score = base_score
        near_support = self._near_level(
            candidate.current_price,
            candidate.support_level or candidate.dma_20 or candidate.dma_50,
            candidate.atr,
        )
        near_resistance = self._near_level(
            candidate.current_price,
            candidate.resistance_level,
            candidate.atr,
        )
        volume_confirmed = self._volume_confirmed(price_volume)
        bullish = pattern in {
            "BULLISH_ENGULFING",
            "HAMMER",
            "MORNING_STAR",
            "STRONG_BULLISH_CLOSE",
            "PIN_BAR_REJECTION",
        }
        bearish = pattern in {
            "BEARISH_ENGULFING",
            "SHOOTING_STAR",
            "EVENING_STAR",
            "STRONG_BEARISH_CLOSE",
        }
        if bullish and near_support:
            score += Decimal("0.12")
        if bullish and price_volume.price_evidence.retracement_state == "HEALTHY":
            score += Decimal("0.10")
        if (
            bullish
            and price_volume.price_evidence.breakout_state == "BREAKOUT"
            and volume_confirmed
        ):
            score += Decimal("0.14")
        if bearish and near_resistance:
            score -= Decimal("0.18")
        if bearish and candidate.breakout_attempt and not price_volume.supports_buy:
            score -= Decimal("0.14")
        if pattern == "DOJI":
            score = min(score, Decimal("0.54"))
        if pattern != "NONE" and not volume_confirmed:
            score = (
                min(score, Decimal("0.58")) if bullish else min(score, Decimal("0.45"))
            )
        if (
            bearish
            and near_resistance
            and price_volume.volume_evidence.volume_vs_average >= Decimal("1.50")
        ):
            score = min(score, Decimal("0.25"))
        if not price_volume.supports_buy and bullish:
            score = min(score, Decimal("0.62"))
        return _bounded_ratio(score)

    def _base_score(self, pattern: str) -> Decimal:
        if pattern in {"BULLISH_ENGULFING", "MORNING_STAR"}:
            return Decimal("0.74")
        if pattern in {"HAMMER", "STRONG_BULLISH_CLOSE"}:
            return Decimal("0.68")
        if pattern in {"BEARISH_ENGULFING", "EVENING_STAR"}:
            return Decimal("0.26")
        if pattern in {"SHOOTING_STAR", "STRONG_BEARISH_CLOSE"}:
            return Decimal("0.30")
        if pattern == "DOJI":
            return Decimal("0.50")
        if pattern in {"INSIDE_BAR", "OUTSIDE_BAR", "PIN_BAR_REJECTION"}:
            return Decimal("0.55")
        return Decimal("0.75")

    def _confirmation(
        self,
        price_volume: PriceVolumeAssessment,
        pattern: str,
        score: Decimal,
    ) -> str:
        if pattern == "NONE":
            return "NEUTRAL"
        if score >= Decimal("0.60") and price_volume.supports_buy:
            return "CONFIRMS"
        if score <= Decimal("0.40") or price_volume.supports_sell:
            return "CONFLICTS"
        return "WEAK"

    def _volume_confirmed(self, price_volume: PriceVolumeAssessment) -> bool:
        return price_volume.volume_evidence.breakout_volume_confirmation >= Decimal(
            "0.60"
        ) or price_volume.volume_evidence.volume_vs_average >= Decimal("1.20")

    def _is_morning_star(self, candidate: RecommendationCandidate) -> bool:
        if (
            candidate.two_day_prior_open_price is None
            or candidate.two_day_prior_close is None
            or candidate.previous_open_price is None
            or candidate.previous_close is None
            or candidate.current_price is None
        ):
            return False
        first_bearish = (
            candidate.two_day_prior_close < candidate.two_day_prior_open_price
        )
        small_middle = self._body(
            candidate.previous_open_price,
            candidate.previous_close,
        ) <= self._body(
            candidate.two_day_prior_open_price,
            candidate.two_day_prior_close,
        ) * Decimal("0.50")
        final_bullish = candidate.current_price > _value_or(
            candidate.open_price,
            candidate.current_price,
        )
        return first_bearish and small_middle and final_bullish

    def _is_evening_star(self, candidate: RecommendationCandidate) -> bool:
        if (
            candidate.two_day_prior_open_price is None
            or candidate.two_day_prior_close is None
            or candidate.previous_open_price is None
            or candidate.previous_close is None
            or candidate.current_price is None
        ):
            return False
        first_bullish = (
            candidate.two_day_prior_close > candidate.two_day_prior_open_price
        )
        small_middle = self._body(
            candidate.previous_open_price,
            candidate.previous_close,
        ) <= self._body(
            candidate.two_day_prior_open_price,
            candidate.two_day_prior_close,
        ) * Decimal("0.50")
        final_bearish = candidate.current_price < _value_or(
            candidate.open_price,
            candidate.current_price,
        )
        return first_bullish and small_middle and final_bearish

    def _has_current_candle(self, candidate: RecommendationCandidate) -> bool:
        return (
            candidate.open_price is not None
            and candidate.high_price is not None
            and candidate.low_price is not None
            and candidate.current_price is not None
        )

    def _is_bullish(self, open_price: Decimal | None, close: Decimal | None) -> bool:
        return open_price is not None and close is not None and close > open_price

    def _is_bearish(self, open_price: Decimal | None, close: Decimal | None) -> bool:
        return open_price is not None and close is not None and close < open_price

    def _body(self, open_price: Decimal | None, close: Decimal | None) -> Decimal:
        if open_price is None or close is None:
            return _ZERO
        return abs(close - open_price)

    def _range(self, high: Decimal | None, low: Decimal | None) -> Decimal:
        if high is None or low is None:
            return _ZERO
        return max(high - low, _ZERO)

    def _upper_wick(self, candidate: RecommendationCandidate) -> Decimal:
        if (
            candidate.high_price is None
            or candidate.open_price is None
            or candidate.current_price is None
        ):
            return _ZERO
        return candidate.high_price - max(candidate.open_price, candidate.current_price)

    def _lower_wick(self, candidate: RecommendationCandidate) -> Decimal:
        if (
            candidate.low_price is None
            or candidate.open_price is None
            or candidate.current_price is None
        ):
            return _ZERO
        return min(candidate.open_price, candidate.current_price) - candidate.low_price

    def _close_strength(self, candidate: RecommendationCandidate) -> Decimal:
        if (
            candidate.high_price is None
            or candidate.low_price is None
            or candidate.current_price is None
        ):
            return Decimal("0.50")
        candle_range = candidate.high_price - candidate.low_price
        if candle_range <= _ZERO:
            return Decimal("0.50")
        return _bounded_ratio(
            (candidate.current_price - candidate.low_price) / candle_range
        )

    def _near_level(
        self,
        price: Decimal | None,
        level: Decimal | None,
        atr: Decimal | None,
    ) -> bool:
        if price is None or level is None:
            return False
        tolerance = (
            (atr * Decimal("1.50"))
            if atr is not None
            else max(
                price * Decimal("0.02"),
                Decimal("1"),
            )
        )
        return abs(price - level) <= tolerance


class EvidenceScoringEngine:
    """Build deterministic technical evidence used by recommendation scoring."""

    def assess(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
    ) -> EvidenceAssessment:
        setup_quality = self._setup_quality(candidate)
        weights = self._weights()
        signals = (
            self._price_level_signal(
                label="Price structure",
                score=price_volume.price_evidence.price_score,
                weight=weights["price_structure"],
                rationale="Price action is the primary source for structure.",
            ),
            self._price_level_signal(
                label="Volume confirmation",
                score=price_volume.volume_evidence.volume_score,
                weight=weights["volume"],
                rationale="Volume confirms or rejects the price move.",
            ),
            self._price_level_signal(
                label="Trend alignment",
                score=self._trend_alignment_score(candidate, price_volume),
                weight=weights["trend"],
                rationale="Moving-average alignment is derived from price behavior.",
            ),
            self._price_level_signal(
                label="Relative strength vs benchmark",
                score=candidate.benchmark_relative_strength
                or candidate.relative_strength_score
                or candidate.probability_score,
                weight=weights["relative_strength"],
                rationale="Relative strength measures leadership versus benchmark.",
            ),
            self._price_level_signal(
                label="Retracement quality",
                score=self._price_volume_retracement_score(candidate, price_volume),
                weight=weights["retracement"],
                rationale="Retracement quality is confirmed by price and volume.",
            ),
            self._price_level_signal(
                label="Candle pattern confirmation",
                score=candle_pattern.score,
                weight=weights["candle"],
                rationale="Candle pattern confirms or conflicts with price-volume.",
            ),
            self._price_level_signal(
                label="Breakout quality",
                score=_bounded_ratio(
                    (
                        (candidate.breakout_setup_score or candidate.strategy_score)
                        + setup_quality.score
                        + price_volume.volume_evidence.breakout_volume_confirmation
                    )
                    / Decimal("3")
                ),
                weight=weights["breakout"],
                rationale="Breakout quality requires price and volume confirmation.",
            ),
            self._price_level_signal(
                label="Market regime",
                score=self._market_regime_score(candidate),
                weight=weights["market_regime"],
                rationale="Market regime adjusts long-side quality threshold.",
            ),
            self._price_level_signal(
                label="Sector strength",
                score=candidate.sector_strength_score
                or candidate.market_intelligence_score,
                weight=weights["sector"],
                rationale="Sector strength captures group-level sponsorship.",
            ),
            self._price_level_signal(
                label="Volatility/risk quality",
                score=_bounded_ratio(
                    (
                        candidate.risk_score
                        + self._volatility_quality_score(price_volume)
                    )
                    / Decimal("2")
                ),
                weight=weights["risk"],
                rationale="Risk quality is adjusted for price volatility behavior.",
            ),
        )
        conflict_penalty = self._conflict_penalty(signals)
        regime_adjustment, regime_reason = self._regime_adjustment(
            candidate,
            setup_quality,
            signals,
        )
        raw_score = sum((signal.points for signal in signals), _ZERO)
        score = max(
            _ZERO,
            min(_HUNDRED, raw_score + regime_adjustment - conflict_penalty),
        )
        confidence_score = _bounded_ratio(score / _HUNDRED)

        return EvidenceAssessment(
            signals=signals,
            score=score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            confidence_score=confidence_score,
            conflict_penalty_points=_quantize(conflict_penalty),
            regime_adjustment_points=_quantize(regime_adjustment),
            regime_reason=regime_reason,
            setup_quality=setup_quality,
            historical_expectancy=HistoricalExpectancy(
                win_rate=candidate.historical_win_rate,
                average_gain=candidate.historical_average_gain,
                average_loss=candidate.historical_average_loss,
                expected_value=candidate.historical_expected_value,
                average_hold_period_days=candidate.historical_average_hold_days,
            ),
            price_volume=price_volume,
            candle_pattern=candle_pattern,
        )

    def _price_level_signal(
        self,
        *,
        label: str,
        score: Decimal,
        weight: Decimal,
        rationale: str,
    ) -> EvidenceSignal:
        normalized_score = _bounded_ratio(score)
        points = normalized_score * weight * _HUNDRED
        direction = EvidenceDirection.NEUTRAL
        if normalized_score >= Decimal("0.60"):
            direction = EvidenceDirection.BULLISH
        elif normalized_score <= Decimal("0.40"):
            direction = EvidenceDirection.BEARISH
        return EvidenceSignal(
            label=label,
            direction=direction,
            score=normalized_score,
            weight=weight,
            points=_quantize(points),
            rationale=rationale,
        )

    def _trend_alignment_score(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> Decimal:
        trend_from_price = price_volume.price_evidence.price_score
        indicator_score = candidate.trend_structure_score or candidate.strategy_score
        return _bounded_ratio(
            trend_from_price * Decimal("0.70") + indicator_score * Decimal("0.30")
        )

    def _setup_quality(
        self,
        candidate: RecommendationCandidate,
    ) -> SetupQualityAssessment:
        setup_type = candidate.setup_type or self._infer_setup_type(candidate)
        base_score = candidate.breakout_setup_score or candidate.strategy_score
        classification = "CONSTRUCTIVE"
        rationale = "Setup has usable technical confirmation."

        if setup_type in {"EMA_PULLBACK", "PULLBACK"}:
            base_score = _bounded_ratio(
                (base_score + candidate.retracement_score) / Decimal("2")
            )
            rationale = "EMA pullback quality uses setup and retracement evidence."
        elif setup_type in {"BREAKOUT", "VOLUME_BREAKOUT"}:
            volume = candidate.volume_confirmation_score or candidate.liquidity_score
            base_score = _bounded_ratio((base_score + volume) / Decimal("2"))
            rationale = "Breakout quality requires setup and volume confirmation."
        elif setup_type == "52_WEEK_HIGH":
            momentum = candidate.momentum_confirmation_score or candidate.strategy_score
            base_score = _bounded_ratio((base_score + momentum) / Decimal("2"))
            rationale = "52-week high quality uses breakout and momentum evidence."
        elif setup_type in {"WEAK_RANDOM", "RANDOM", "WEAK"}:
            base_score = min(base_score, Decimal("0.30"))
            classification = "WEAK"
            rationale = "Weak/random setup is penalized deterministically."

        if base_score >= Decimal("0.80"):
            classification = "HIGH"
        elif base_score <= Decimal("0.40"):
            classification = "WEAK"

        return SetupQualityAssessment(
            setup_type=setup_type,
            score=base_score,
            classification=classification,
            rationale=rationale,
        )

    def _infer_setup_type(self, candidate: RecommendationCandidate) -> str:
        if candidate.retracement_score >= Decimal("0.75"):
            return "EMA_PULLBACK"
        if (candidate.breakout_setup_score or candidate.strategy_score) >= Decimal(
            "0.80"
        ):
            return "BREAKOUT"
        if (
            candidate.volume_confirmation_score
            and candidate.volume_confirmation_score >= Decimal("0.80")
        ):
            return "VOLUME_BREAKOUT"
        if candidate.strategy_score <= Decimal("0.35"):
            return "WEAK_RANDOM"
        return "MOMENTUM_CONFIRMATION"

    def _market_regime_score(self, candidate: RecommendationCandidate) -> Decimal:
        base_score = (
            candidate.market_regime_score or candidate.market_intelligence_score
        )
        if candidate.market_regime == "BULL":
            return max(base_score, Decimal("0.65"))
        if candidate.market_regime == "BEAR":
            return min(base_score, Decimal("0.35"))
        return min(base_score, Decimal("0.60"))

    def _price_volume_retracement_score(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> Decimal:
        score = candidate.retracement_score
        if price_volume.price_evidence.retracement_state == "HEALTHY":
            score += Decimal("0.10")
        if price_volume.price_evidence.retracement_state == "BAD":
            score -= Decimal("0.25")
        if price_volume.volume_evidence.volume_dry_up_score >= Decimal("0.60"):
            score += Decimal("0.10")
        if price_volume.volume_evidence.selloff_volume_penalty >= Decimal("0.70"):
            score -= Decimal("0.30")
        return _bounded_ratio(score)

    def _volatility_quality_score(
        self,
        price_volume: PriceVolumeAssessment,
    ) -> Decimal:
        if price_volume.price_evidence.volatility_state == "EXPANDING_RISK":
            return Decimal("0.25")
        if price_volume.price_evidence.volatility_state == "CONTROLLED":
            return Decimal("0.80")
        return Decimal("0.60")

    def _weights(self) -> Mapping[str, Decimal]:
        return {
            "price_structure": Decimal("0.20"),
            "volume": Decimal("0.17"),
            "trend": Decimal("0.15"),
            "relative_strength": Decimal("0.13"),
            "retracement": Decimal("0.10"),
            "candle": Decimal("0.08"),
            "breakout": Decimal("0.07"),
            "market_regime": Decimal("0.05"),
            "sector": Decimal("0.03"),
            "risk": Decimal("0.02"),
        }

    def _conflict_penalty(self, signals: tuple[EvidenceSignal, ...]) -> Decimal:
        bullish_weight = sum(
            (
                signal.weight
                for signal in signals
                if signal.direction is EvidenceDirection.BULLISH
            ),
            _ZERO,
        )
        bearish_weight = sum(
            (
                signal.weight
                for signal in signals
                if signal.direction is EvidenceDirection.BEARISH
            ),
            _ZERO,
        )
        if bullish_weight == _ZERO or bearish_weight == _ZERO:
            return _ZERO
        return min(bullish_weight, bearish_weight) * Decimal("12")

    def _regime_adjustment(
        self,
        candidate: RecommendationCandidate,
        setup_quality: SetupQualityAssessment,
        signals: tuple[EvidenceSignal, ...],
    ) -> tuple[Decimal, str]:
        bearish_count = len(
            tuple(
                signal
                for signal in signals
                if signal.direction is EvidenceDirection.BEARISH
            )
        )
        if candidate.market_regime == "BULL":
            if setup_quality.setup_type in {
                "BREAKOUT",
                "VOLUME_BREAKOUT",
                "52_WEEK_HIGH",
            }:
                return Decimal("4"), "Bull market rewards quality breakout leadership."
            return Decimal("2"), "Bull market rewards trend continuation."
        if candidate.market_regime == "BEAR":
            penalty = Decimal("-8") - Decimal(bearish_count)
            return penalty, "Bear market raises quality threshold for long setups."
        if setup_quality.setup_type in {"BREAKOUT", "VOLUME_BREAKOUT"}:
            return Decimal("-4"), "Sideways market reduces breakout confidence."
        return Decimal("-2"), "Sideways market increases pullback caution."


class RecommendationScoringEngine:
    """Combine deterministic score components into a 0-100 score."""

    def score(
        self,
        *,
        candidate: RecommendationCandidate,
        evidence_assessment: EvidenceAssessment,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
        opportunity_cost: OpportunityCostAssessment,
        allocation: AllocationAdjustment,
    ) -> RecommendationScore:
        evidence_points = evidence_assessment.score

        breakdown = RecommendationScoreBreakdown(
            strategy_points=_ZERO,
            probability_points=_ZERO,
            market_intelligence_points=_ZERO,
            liquidity_points=_ZERO,
            risk_points=_ZERO,
            portfolio_adjustment_points=allocation.adjustment_points,
            opportunity_cost_points=opportunity_cost.opportunity_cost_points,
            retracement_points=self._points_for(
                evidence_assessment,
                "Retracement quality",
            ),
            trend_structure_points=(
                self._points_for(evidence_assessment, "Price structure")
                + self._points_for(evidence_assessment, "Trend alignment")
            ),
            relative_strength_points=self._points_for(
                evidence_assessment,
                "Relative strength vs benchmark",
            ),
            volume_confirmation_points=self._points_for(
                evidence_assessment,
                "Volume confirmation",
            ),
            breakout_setup_points=self._points_for(
                evidence_assessment,
                "Breakout quality",
            ),
            candle_pattern_points=self._points_for(
                evidence_assessment,
                "Candle pattern confirmation",
            ),
            market_regime_points=self._points_for(
                evidence_assessment,
                "Market regime",
            ),
            sector_strength_points=self._points_for(
                evidence_assessment,
                "Sector strength",
            ),
            retracement_weight=self._weight_for(
                evidence_assessment,
                "Retracement quality",
            ),
            candle_weight=candle_pattern.weight,
            evidence_points=evidence_points,
            conflict_penalty_points=evidence_assessment.conflict_penalty_points,
            regime_adjustment_points=evidence_assessment.regime_adjustment_points,
        )
        raw_score = max(
            _ZERO,
            min(
                _HUNDRED,
                evidence_points
                + allocation.adjustment_points
                + opportunity_cost.opportunity_cost_points,
            ),
        )
        raw_score = self._apply_regime_and_risk_overrides(
            candidate,
            price_volume,
            candle_pattern,
            raw_score,
        )
        score = raw_score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        return RecommendationScore(
            symbol=candidate.symbol,
            score=score,
            decision=self._decision(score),
            breakdown=breakdown,
        )

    def _decision(self, score: Decimal) -> RecommendationDecision:
        if score >= Decimal("90"):
            return RecommendationDecision.STRONG_BUY
        if score >= Decimal("75"):
            return RecommendationDecision.BUY
        if score >= Decimal("60"):
            return RecommendationDecision.WATCHLIST
        if score >= Decimal("40"):
            return RecommendationDecision.AVOID
        return RecommendationDecision.SELL

    def _apply_regime_and_risk_overrides(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
        raw_score: Decimal,
    ) -> Decimal:
        score = raw_score
        if candidate.market_regime == "SIDEWAYS" and not _has_buy_confirmation(
            candidate,
        ):
            score = min(score, Decimal("74"))
        if candidate.market_regime == "BEAR" and candidate.retracement_score < Decimal(
            "0.45"
        ):
            score = min(score, Decimal("59"))
        if candidate.risk_score <= Decimal(
            "0.25"
        ) and candidate.strategy_score <= Decimal("0.25"):
            score = min(score, Decimal("39"))
        if _is_below(candidate.current_price, candidate.fibonacci_618):
            score = min(score, Decimal("59"))
        if _is_below(candidate.current_price, candidate.fibonacci_786):
            score = min(score, Decimal("35"))
        if price_volume.override_reasons:
            if price_volume.supports_sell:
                score = min(score, Decimal("39"))
            else:
                score = min(score, Decimal("59"))
        if candle_pattern.confirmation == "CONFLICTS":
            score = min(score, Decimal("59"))
        if (
            candle_pattern.pattern
            in {"BEARISH_ENGULFING", "SHOOTING_STAR", "EVENING_STAR"}
            and candle_pattern.volume_confirmed
            and price_volume.price_evidence.support_resistance_state
            in {"ABOVE_RESISTANCE", "HOLDING_SUPPORT"}
        ):
            score = min(score, Decimal("59"))
        return score

    def _points_for(
        self,
        evidence_assessment: EvidenceAssessment,
        label: str,
    ) -> Decimal:
        return sum(
            (
                signal.points
                for signal in evidence_assessment.signals
                if signal.label == label
            ),
            _ZERO,
        )

    def _weight_for(
        self,
        evidence_assessment: EvidenceAssessment,
        label: str,
    ) -> Decimal:
        for signal in evidence_assessment.signals:
            if signal.label == label:
                return signal.weight
        return _ZERO


class RecommendationEngine:
    """Build sorted, explainable recommendation reports."""

    def __init__(
        self,
        *,
        expected_value_engine: ExpectedValueEngine | None = None,
        price_volume_engine: PriceVolumeSignalEngine | None = None,
        candle_pattern_engine: CandlePatternEngine | None = None,
        evidence_scoring_engine: EvidenceScoringEngine | None = None,
        opportunity_cost_engine: OpportunityCostEngine | None = None,
        portfolio_engine: PortfolioAwarenessEngine | None = None,
        scoring_engine: RecommendationScoringEngine | None = None,
    ) -> None:
        self._expected_value_engine = expected_value_engine or ExpectedValueEngine()
        self._price_volume_engine = price_volume_engine or PriceVolumeSignalEngine()
        self._candle_pattern_engine = candle_pattern_engine or CandlePatternEngine()
        self._evidence_scoring_engine = (
            evidence_scoring_engine or EvidenceScoringEngine()
        )
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
        price_volume = self._price_volume_engine.assess(candidate)
        candle_pattern = self._candle_pattern_engine.assess(
            candidate=candidate,
            price_volume=price_volume,
        )
        evidence_assessment = self._evidence_scoring_engine.assess(
            candidate,
            price_volume,
            candle_pattern,
        )
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
            evidence_assessment=evidence_assessment,
            price_volume=price_volume,
            candle_pattern=candle_pattern,
            opportunity_cost=opportunity_cost,
            allocation=allocation,
        )
        action = self._action_for(score.decision)
        trade_plan = self._trade_plan(
            candidate=candidate,
            score=score,
            evidence_assessment=evidence_assessment,
        )

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
                trade_plan=trade_plan,
                evidence_assessment=evidence_assessment,
            ),
            trade_plan=trade_plan,
            evidence_assessment=evidence_assessment,
            metadata=candidate.metadata,
        )

    def _action_for(
        self,
        decision: RecommendationDecision,
    ) -> RecommendationAction:
        if decision is RecommendationDecision.STRONG_BUY:
            return RecommendationAction.BUY
        if decision is RecommendationDecision.BUY:
            return RecommendationAction.BUY
        if decision is RecommendationDecision.WATCHLIST:
            return RecommendationAction.ACCUMULATE
        if decision is RecommendationDecision.HOLD:
            return RecommendationAction.HOLD
        if decision is RecommendationDecision.SELL:
            return RecommendationAction.AVOID
        return RecommendationAction.AVOID

    def _trade_plan(
        self,
        *,
        candidate: RecommendationCandidate,
        score: RecommendationScore,
        evidence_assessment: EvidenceAssessment,
    ) -> RecommendationTradePlan:
        current_price = _value_or(candidate.current_price, Decimal("0"))
        atr = _value_or(
            candidate.atr,
            max(current_price * Decimal("0.02"), Decimal("1")),
        )
        swing_high = _value_or(
            candidate.swing_high,
            _value_or(candidate.recent_high, current_price),
        )
        swing_low = _value_or(
            candidate.swing_low,
            _value_or(candidate.retracement_low, current_price),
        )
        recent_high = _value_or(candidate.recent_high, swing_high)
        confirmation = _max_decimal(
            current_price,
            _value_or(candidate.prior_day_high, current_price),
            _value_or(candidate.reversal_candle_high, current_price),
        )
        if (
            evidence_assessment.price_evidence.breakout_state == "BREAKOUT"
            and evidence_assessment.volume_evidence.breakout_volume_confirmation
            >= Decimal("0.60")
            and candidate.resistance_level is not None
        ):
            confirmation = max(confirmation, candidate.resistance_level)
        if evidence_assessment.candle_pattern.entry_trigger is not None:
            confirmation = max(
                confirmation,
                evidence_assessment.candle_pattern.entry_trigger,
            )
        support_level, support_name = _support_level(candidate, current_price)
        nearest_fibonacci_level = _nearest_fibonacci(candidate, current_price)
        retracement_low = _value_or(candidate.retracement_low, support_level)
        entry_zone_low = min(support_level, retracement_low)
        if evidence_assessment.volume_evidence.selloff_volume_penalty >= Decimal(
            "0.70"
        ):
            entry_zone_low = confirmation
            entry_zone_high = confirmation
        else:
            entry_zone_high = max(
                support_level,
                min(confirmation, support_level + (atr * Decimal("0.75"))),
            )
        entry_price = max(confirmation, recent_high)
        if (
            candidate.resistance_level is not None
            and evidence_assessment.price_volume.supports_buy
        ):
            entry_price = max(entry_price, candidate.resistance_level)
        structure_stop = min(retracement_low, support_level) - (atr * Decimal("0.25"))
        if evidence_assessment.candle_pattern.stop_level is not None:
            structure_stop = min(
                structure_stop,
                evidence_assessment.candle_pattern.stop_level,
            )
        atr_stop = support_level - (atr * Decimal("1.5"))
        dma_50_stop = (
            candidate.dma_50 - (atr * Decimal("0.25"))
            if candidate.dma_50 is not None
            else structure_stop
        )
        dma_stop = (
            candidate.dma_20 - (atr * Decimal("0.25"))
            if candidate.dma_20 is not None
            else structure_stop
        )
        initial_stop = min(structure_stop, atr_stop, dma_stop, dma_50_stop)
        invalidation_level, invalidation_reason = _invalidation(
            candidate,
            support_level,
        )
        if evidence_assessment.candle_pattern.invalidation_level is not None:
            invalidation_level = min(
                invalidation_level,
                evidence_assessment.candle_pattern.invalidation_level,
            )
            invalidation_reason = (
                "close below candle low or support invalidates the setup"
            )
        risk = max(entry_price - initial_stop, Decimal("0.01"))
        target_1 = entry_price + (risk * Decimal("2"))
        target_2 = entry_price + (risk * Decimal("3"))
        measured_move = entry_price + max(swing_high - swing_low, atr)
        target_3 = max(
            swing_high,
            measured_move,
            entry_price + (atr * Decimal("3")),
        )
        reward = target_1 - entry_price
        confidence = _confidence(score.score)
        confidence_percent = _as_percent(evidence_assessment.confidence_score)
        trailing_stop_strategy = (
            f"Trail at 2 x ATR ({atr * Decimal('2')}) below the highest close "
            "after entry."
        )
        dma_20_invalidation = candidate.dma_20 or candidate.ema_20
        reported_dma_20_invalidation = (
            dma_20_invalidation
            if dma_20_invalidation is not None
            else invalidation_level
        )
        dma_20_text = (
            "Trade invalid if daily close is below the active invalidation "
            f"level, currently ₹{_money(reported_dma_20_invalidation)}."
        )
        if dma_20_invalidation is not None:
            dma_20_text = (
                "Trade invalid if daily close is below 20-DMA, currently "
                f"₹{_money(dma_20_invalidation)}."
            )
        retracement_effect = (
            "improved"
            if score.breakdown.retracement_points >= Decimal("4")
            else "reduced"
            if score.breakdown.retracement_points < Decimal("3")
            else "kept neutral"
        )
        explanation = (
            f"{score.decision.value} because the final score is {score.score}/100. "
            f"Price action is {evidence_assessment.price_evidence.structure_state} "
            f"with {evidence_assessment.price_evidence.breakout_state}. "
            f"Volume is scoring {evidence_assessment.volume_evidence.volume_score} "
            "as confirmation. "
            f"Candle pattern {evidence_assessment.candle_pattern.pattern} "
            f"{evidence_assessment.candle_pattern.confirmation.lower()} "
            "the setup. "
            f"Retracement {retracement_effect} the signal with "
            f"{score.breakdown.retracement_points} weighted points. "
            f"Support used: {support_name} at {support_level}. "
            f"Entry zone: {entry_zone_low} to {entry_zone_high}; confirmation entry: "
            f"{entry_price}. Stop loss: {initial_stop}. Invalidation: "
            f"{invalidation_level} ({invalidation_reason}). Targets: {target_1}, "
            f"{target_2}, {target_3}. {dma_20_text} {trailing_stop_strategy} "
            "Volume condition: breakout or bounce must confirm above average volume. "
            f"Confidence: {confidence_percent}."
        )

        return RecommendationTradePlan(
            final_signal=score.decision.value,
            final_score=score.score,
            confidence=confidence,
            entry_price=_money(entry_price),
            entry_zone_low=_money(entry_zone_low),
            entry_zone_high=_money(entry_zone_high),
            initial_stop_loss=_money(initial_stop),
            trailing_stop_strategy=trailing_stop_strategy,
            target_1=_money(target_1),
            target_2=_money(target_2),
            target_3=_money(target_3),
            risk_reward_ratio=_quantize(reward / risk),
            invalidation_level=_money(invalidation_level),
            invalidation_reason=invalidation_reason,
            retracement_score=candidate.retracement_score,
            retracement_weight=score.breakdown.retracement_weight,
            retracement_zone=support_name,
            nearest_fibonacci_level=_money(nearest_fibonacci_level),
            swing_high=_money(swing_high),
            swing_low=_money(swing_low),
            support_level_used=_money(support_level),
            atr_value=_money(atr),
            dma_20_invalidation=_money(reported_dma_20_invalidation),
            candle_pattern=evidence_assessment.candle_pattern.pattern,
            candle_score=evidence_assessment.candle_pattern.score,
            candle_weight=evidence_assessment.candle_pattern.weight,
            candle_confirmation=evidence_assessment.candle_pattern.confirmation,
            candle_entry_trigger=(
                _money(evidence_assessment.candle_pattern.entry_trigger)
                if evidence_assessment.candle_pattern.entry_trigger is not None
                else None
            ),
            candle_stop_level=(
                _money(evidence_assessment.candle_pattern.stop_level)
                if evidence_assessment.candle_pattern.stop_level is not None
                else None
            ),
            candle_invalidation_level=(
                _money(evidence_assessment.candle_pattern.invalidation_level)
                if evidence_assessment.candle_pattern.invalidation_level is not None
                else None
            ),
            candle_explanation=evidence_assessment.candle_pattern.explanation,
            trade_plan_explanation=explanation,
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
        trade_plan: RecommendationTradePlan,
        evidence_assessment: EvidenceAssessment,
    ) -> tuple[str, ...]:
        lines = [
            f"{candidate.symbol}: {score.decision.value}",
            f"Recommendation Score: {score.score}/100",
            f"Evidence Score: {evidence_assessment.score}/100",
            f"Confidence Score: {_as_percent(evidence_assessment.confidence_score)}",
            f"Action: {action.value}",
            "Why this ranks here:",
            f"- Setup quality: {evidence_assessment.setup_quality.classification}",
            f"- Setup type: {evidence_assessment.setup_quality.setup_type}",
            f"- Setup rationale: {evidence_assessment.setup_quality.rationale}",
            (
                "- Price action: "
                f"{evidence_assessment.price_evidence.trend_state}, "
                f"{evidence_assessment.price_evidence.structure_state}, "
                f"{evidence_assessment.price_evidence.breakout_state}"
            ),
            (
                "- Volume action: "
                f"vs average {evidence_assessment.volume_evidence.volume_vs_average}, "
                f"score {evidence_assessment.volume_evidence.volume_score}"
            ),
            (
                "- Price-volume verdict: "
                f"supports_buy={evidence_assessment.price_volume.supports_buy}, "
                f"supports_sell={evidence_assessment.price_volume.supports_sell}"
            ),
            (
                "- Candle pattern: "
                f"{evidence_assessment.candle_pattern.pattern}, "
                f"{evidence_assessment.candle_pattern.confirmation}, "
                f"score {evidence_assessment.candle_pattern.score}"
            ),
            (
                "- Candle levels: "
                f"entry {trade_plan.candle_entry_trigger}, "
                f"stop {trade_plan.candle_stop_level}, "
                f"invalidation {trade_plan.candle_invalidation_level}"
            ),
            (
                "- Candle volume confirmation: "
                f"{evidence_assessment.candle_pattern.volume_confirmed}"
            ),
            (f"- Candle explanation: {evidence_assessment.candle_pattern.explanation}"),
            f"- Regime adjustment: {evidence_assessment.regime_reason}",
            (
                "- Conflict penalty: "
                f"{evidence_assessment.conflict_penalty_points} points"
            ),
            (
                "- Retracement contribution: "
                f"{_as_percent(candidate.retracement_score)} quality at "
                f"{_as_percent(trade_plan.retracement_weight)} weight"
            ),
            (
                "- Expected value: "
                f"{_as_percent(expected_value.expected_return)} return, "
                f"{_as_percent(expected_value.expected_drawdown)} drawdown"
            ),
            (
                "- Opportunity cost: "
                f"rank {opportunity_cost.rank} of "
                f"{opportunity_cost.candidate_count}"
            ),
            (f"- Suggested allocation: {allocation.adjusted_allocation_percent}%"),
            f"Support level used: {trade_plan.support_level_used}",
            (
                "Entry zone: "
                f"{trade_plan.entry_zone_low} to {trade_plan.entry_zone_high}"
            ),
            f"Confirmation entry: {trade_plan.entry_price}",
            f"Initial stop loss: {trade_plan.initial_stop_loss}",
            f"ATR value: {trade_plan.atr_value}",
            (
                "Invalidation level: "
                f"{trade_plan.invalidation_level} - {trade_plan.invalidation_reason}"
            ),
            (
                "20-DMA invalidation: "
                f"{_dma_20_invalidation_text(trade_plan.dma_20_invalidation)}"
            ),
            (
                "Targets: "
                f"{trade_plan.target_1}, {trade_plan.target_2}, "
                f"{trade_plan.target_3}"
            ),
            f"Trailing stop: {trade_plan.trailing_stop_strategy}",
            (
                "Volume confirmation required: breakout or bounce must occur "
                "on above-average volume."
            ),
            f"Trade plan: {trade_plan.trade_plan_explanation}",
            "Bullish evidence:",
        ]

        for reason in evidence_assessment.price_volume.override_reasons:
            lines.append(f"Price-volume override: {reason}")

        for signal in evidence_assessment.bullish_signals:
            lines.append(
                f"- {signal.label}: {signal.points} points - {signal.rationale}"
            )

        lines.append("Bearish evidence:")
        for signal in evidence_assessment.bearish_signals:
            lines.append(
                f"- {signal.label}: {signal.points} points - {signal.rationale}"
            )

        lines.append("Top evidence contributors:")
        for signal in evidence_assessment.top_contributors:
            lines.append(
                f"- {signal.label}: {signal.points} points "
                f"({_as_percent(signal.weight)} weight)"
            )

        lines.append(
            f"Historical expectancy: {evidence_assessment.historical_expectancy.status}"
        )

        for evidence in candidate.evidence:
            lines.append(f"Support: {evidence.label} - {evidence.rationale}")

        for risk in candidate.risks:
            lines.append(f"Risk: {risk.label} - {risk.rationale}")

        return tuple(lines)


def _drawdown_quality(value: Decimal) -> Decimal:
    drawdown = Decimal(str(value))
    if drawdown <= _ZERO:
        return _ONE
    if drawdown >= Decimal("0.20"):
        return _ZERO
    return _ONE - (drawdown / Decimal("0.20"))


def _positive_ratio(value: Decimal) -> Decimal:
    if value <= _ZERO:
        return _ZERO
    return min(value, _ONE)


def _bounded_ratio(value: Decimal) -> Decimal:
    if value < _ZERO:
        return _ZERO
    if value > _ONE:
        return _ONE
    return _quantize(value)


def _value_or(value: Decimal | None, fallback: Decimal) -> Decimal:
    if value is None:
        return fallback
    return Decimal(str(value))


def _is_below(value: Decimal | None, level: Decimal | None) -> bool:
    if value is None or level is None:
        return False
    return Decimal(str(value)) < Decimal(str(level))


def _has_buy_confirmation(candidate: RecommendationCandidate) -> bool:
    if candidate.current_price is None:
        return True
    confirmation = max(
        _value_or(candidate.prior_day_high, candidate.current_price),
        _value_or(candidate.reversal_candle_high, candidate.current_price),
    )
    return candidate.current_price >= confirmation


def _max_decimal(*values: Decimal) -> Decimal:
    return max(Decimal(str(value)) for value in values)


def _support_level(
    candidate: RecommendationCandidate,
    fallback: Decimal,
) -> tuple[Decimal, str]:
    candidates: list[tuple[Decimal, str]] = []
    if candidate.dma_20 is not None:
        candidates.append((candidate.dma_20, "20-DMA"))
    if candidate.dma_50 is not None:
        candidates.append((candidate.dma_50, "50-DMA"))
    if candidate.fibonacci_382 is not None:
        candidates.append((candidate.fibonacci_382, "38.2% Fibonacci"))
    if candidate.fibonacci_500 is not None:
        candidates.append((candidate.fibonacci_500, "50% Fibonacci"))
    if candidate.retracement_low is not None:
        candidates.append((candidate.retracement_low, "retracement low"))
    if not candidates:
        return fallback, "current price"
    current = _value_or(candidate.current_price, fallback)
    return min(candidates, key=lambda item: abs(item[0] - current))


def _nearest_fibonacci(
    candidate: RecommendationCandidate,
    fallback: Decimal,
) -> Decimal:
    levels = tuple(
        level
        for level in (
            candidate.fibonacci_382,
            candidate.fibonacci_500,
            candidate.fibonacci_618,
            candidate.fibonacci_786,
        )
        if level is not None
    )
    if not levels:
        return fallback
    current = _value_or(candidate.current_price, fallback)
    return min(levels, key=lambda level: abs(level - current))


def _invalidation(
    candidate: RecommendationCandidate,
    support_level: Decimal,
) -> tuple[Decimal, str]:
    if candidate.fibonacci_786 is not None and _is_below(
        candidate.current_price,
        candidate.fibonacci_786,
    ):
        return (
            candidate.fibonacci_786,
            "strong invalidation: close below 78.6% Fibonacci retracement",
        )
    if candidate.fibonacci_618 is not None:
        return (
            candidate.fibonacci_618,
            "close below 61.8% Fibonacci retracement invalidates the pullback",
        )
    if candidate.dma_20 is not None:
        return candidate.dma_20, "close below 20-DMA invalidates the setup"
    if candidate.dma_50 is not None:
        return candidate.dma_50, "close below 50-DMA invalidates the pullback"
    return support_level, "close below selected support invalidates the setup"


def _confidence(score: Decimal) -> str:
    if score >= Decimal("75"):
        return "HIGH"
    if score >= Decimal("60"):
        return "MEDIUM"
    if score >= Decimal("40"):
        return "LOW"
    return "REJECT"


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _metadata_decimal(
    candidate: RecommendationCandidate,
    key: str,
) -> Decimal | None:
    value = candidate.metadata.get(key)
    if value is None:
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _dma_20_invalidation_text(level: Decimal | None) -> str:
    if level is None:
        return "Trade invalidation unavailable because 20-DMA is unavailable."
    return f"Trade invalid if daily close is below 20-DMA, currently ₹{level}."


def _quantize(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def _as_percent(value: Decimal) -> str:
    percentage = (Decimal(str(value)) * _HUNDRED).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return f"{percentage}%"
