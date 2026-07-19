from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from alpha.recommendation_intelligence.models import (
    AllocationAdjustment,
    CandidateComparison,
    CandlePatternAssessment,
    EdgeConfidence,
    EntryTriggerStyle,
    EntryZoneBasis,
    EntryZoneBasisType,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceSignal,
    ExpectedValueAssessment,
    HistoricalExpectancy,
    OHLCVBar,
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
    StrategyEdgeStats,
    StrategyQuality,
    StrategyRank,
    TradeSetupAssessment,
    TradeStrategyAction,
    TradeStrategyPlaybook,
    TradeStrategyType,
    TriggerStatus,
    VolumeEvidence,
)
from alpha.strategy_regime import recommendation_historical_edge_metadata

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class FibonacciRetracementLevels:
    level_236: Decimal | None
    level_382: Decimal | None
    level_500: Decimal | None
    level_618: Decimal | None
    level_786: Decimal | None

    @property
    def available_levels(self) -> tuple[Decimal, ...]:
        return tuple(
            level
            for level in (
                self.level_236,
                self.level_382,
                self.level_500,
                self.level_618,
                self.level_786,
            )
            if level is not None
        )


@dataclass(frozen=True, slots=True)
class TradePlanMarketLevels:
    historical_bar_count: int
    latest_close: Decimal | None
    latest_high: Decimal | None
    latest_low: Decimal | None
    dma_20: Decimal | None
    dma_50: Decimal | None
    dma_200: Decimal | None
    atr_14: Decimal | None
    recent_swing_high: Decimal | None
    recent_swing_low: Decimal | None
    nearest_support: Decimal | None
    nearest_support_name: str
    nearest_resistance: Decimal | None
    fibonacci: FibonacciRetracementLevels
    nearest_fibonacci_level: Decimal | None
    retracement_zone: str
    relative_volume: Decimal | None
    unavailable_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TradePlanLevelAssessment:
    market_levels: TradePlanMarketLevels
    entry_price: Decimal | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    initial_stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    risk_reward_ratio: Decimal | None
    invalidation_level: Decimal | None
    invalidation_reason: str
    trailing_stop_strategy: str
    trade_plan_explanation: str


class TradePlanIntelligenceEngine:
    """Calculate actionable trade levels from real OHLCV inputs."""

    def assess(
        self,
        *,
        candidate: RecommendationCandidate,
        score: RecommendationScore,
        evidence_assessment: EvidenceAssessment,
    ) -> TradePlanLevelAssessment:
        levels = self.market_levels(candidate)
        is_actionable = score.decision in {
            RecommendationDecision.STRONG_BUY,
            RecommendationDecision.BUY,
            RecommendationDecision.WATCHLIST,
        }
        entry_price: Decimal | None = None
        entry_zone_low: Decimal | None = None
        entry_zone_high: Decimal | None = None

        if is_actionable:
            if self._is_breakout_setup(candidate, evidence_assessment, levels):
                entry_price = levels.nearest_resistance
                entry_zone_low = entry_price
                entry_zone_high = self._add_atr(entry_price, levels.atr_14, "0.50")
            elif self._is_retracement_setup(candidate, evidence_assessment, levels):
                entry_price = self._confirmation_trigger(candidate, levels)
                entry_zone_low = levels.nearest_support
                entry_zone_high = self._add_atr(
                    levels.nearest_support,
                    levels.atr_14,
                    "0.50",
                )

        initial_stop = self._stop_loss(
            candidate=candidate,
            entry_price=entry_price,
            levels=levels,
            evidence_assessment=evidence_assessment,
        )
        target_1, target_2, target_3, risk_reward_ratio = self._targets(
            entry_price=entry_price,
            initial_stop=initial_stop,
            levels=levels,
        )
        invalidation_level, invalidation_reason = self._invalidation(levels)
        trailing_stop_strategy = self._trailing_stop_strategy(levels.atr_14)
        explanation = self._explanation(
            score=score,
            evidence_assessment=evidence_assessment,
            levels=levels,
            entry_price=entry_price,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            initial_stop=initial_stop,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            invalidation_level=invalidation_level,
            invalidation_reason=invalidation_reason,
            trailing_stop_strategy=trailing_stop_strategy,
        )

        return TradePlanLevelAssessment(
            market_levels=levels,
            entry_price=_money_optional(entry_price),
            entry_zone_low=_money_optional(entry_zone_low),
            entry_zone_high=_money_optional(entry_zone_high),
            initial_stop_loss=_money_optional(initial_stop),
            target_1=_money_optional(target_1),
            target_2=_money_optional(target_2),
            target_3=_money_optional(target_3),
            risk_reward_ratio=(
                _quantize(risk_reward_ratio) if risk_reward_ratio is not None else None
            ),
            invalidation_level=_money_optional(invalidation_level),
            invalidation_reason=invalidation_reason,
            trailing_stop_strategy=trailing_stop_strategy,
            trade_plan_explanation=explanation,
        )

    def market_levels(
        self,
        candidate: RecommendationCandidate,
    ) -> TradePlanMarketLevels:
        bars = self._bars(candidate)
        latest = bars[-1] if bars else None
        latest_close = (
            latest.close_price if latest is not None else candidate.current_price
        )
        latest_high = latest.high_price if latest is not None else candidate.high_price
        latest_low = latest.low_price if latest is not None else candidate.low_price
        dma_20 = candidate.dma_20 or self._moving_average(bars, 20)
        dma_50 = candidate.dma_50 or self._moving_average(bars, 50)
        dma_200 = candidate.dma_200 or self._moving_average(bars, 200)
        atr_14 = candidate.atr or self._atr(bars, 14)
        swing_high = candidate.swing_high or self._swing_high(bars)
        swing_low = candidate.swing_low or self._swing_low(bars)
        fibonacci = self._fibonacci(candidate, swing_low, swing_high)
        nearest_fibonacci = self._nearest_level(
            latest_close,
            fibonacci.available_levels,
        )
        nearest_support, support_name = self._nearest_support(
            candidate=candidate,
            latest_close=latest_close,
            dma_20=dma_20,
            dma_50=dma_50,
            swing_low=swing_low,
            fibonacci=fibonacci,
        )
        nearest_resistance = self._nearest_resistance(
            candidate=candidate,
            latest_close=latest_close,
            swing_high=swing_high,
        )

        return TradePlanMarketLevels(
            historical_bar_count=len(bars),
            latest_close=_money_optional(latest_close),
            latest_high=_money_optional(latest_high),
            latest_low=_money_optional(latest_low),
            dma_20=_money_optional(dma_20),
            dma_50=_money_optional(dma_50),
            dma_200=_money_optional(dma_200),
            atr_14=_money_optional(atr_14),
            recent_swing_high=_money_optional(swing_high),
            recent_swing_low=_money_optional(swing_low),
            nearest_support=_money_optional(nearest_support),
            nearest_support_name=support_name,
            nearest_resistance=_money_optional(nearest_resistance),
            fibonacci=FibonacciRetracementLevels(
                level_236=_money_optional(fibonacci.level_236),
                level_382=_money_optional(fibonacci.level_382),
                level_500=_money_optional(fibonacci.level_500),
                level_618=_money_optional(fibonacci.level_618),
                level_786=_money_optional(fibonacci.level_786),
            ),
            nearest_fibonacci_level=_money_optional(nearest_fibonacci),
            retracement_zone=self._retracement_zone(
                latest_close,
                swing_low,
                swing_high,
            ),
            relative_volume=_optional_quantize(self._relative_volume(bars)),
            unavailable_reasons=self._unavailable_reasons(
                bar_count=len(bars),
                dma_20=dma_20,
                dma_50=dma_50,
                dma_200=dma_200,
                atr_14=atr_14,
                swing_high=swing_high,
                swing_low=swing_low,
            ),
        )

    def _bars(self, candidate: RecommendationCandidate) -> tuple[OHLCVBar, ...]:
        if candidate.price_history:
            return candidate.price_history
        if (
            candidate.open_price is None
            or candidate.high_price is None
            or candidate.low_price is None
            or candidate.current_price is None
        ):
            return ()
        if (
            candidate.high_price < candidate.low_price
            or candidate.open_price > candidate.high_price
            or candidate.open_price < candidate.low_price
            or candidate.current_price > candidate.high_price
            or candidate.current_price < candidate.low_price
        ):
            return ()
        return (
            OHLCVBar(
                observed_on=candidate.observed_on,
                open_price=candidate.open_price,
                high_price=candidate.high_price,
                low_price=candidate.low_price,
                close_price=candidate.current_price,
                volume=Decimal("0"),
            ),
        )

    def _moving_average(
        self,
        bars: tuple[OHLCVBar, ...],
        period: int,
    ) -> Decimal | None:
        if len(bars) < period:
            return None
        closes = tuple(bar.close_price for bar in bars[-period:])
        return sum(closes, _ZERO) / Decimal(period)

    def _atr(
        self,
        bars: tuple[OHLCVBar, ...],
        period: int,
    ) -> Decimal | None:
        if len(bars) <= period:
            return None
        ranges: list[Decimal] = []
        for index in range(len(bars) - period, len(bars)):
            bar = bars[index]
            previous_close = bars[index - 1].close_price
            ranges.append(
                max(
                    bar.high_price - bar.low_price,
                    abs(bar.high_price - previous_close),
                    abs(bar.low_price - previous_close),
                )
            )
        return sum(ranges, _ZERO) / Decimal(period)

    def _relative_volume(self, bars: tuple[OHLCVBar, ...]) -> Decimal | None:
        if len(bars) < 20:
            return None
        latest_volume = bars[-1].volume
        average_volume = self._average_volume(bars)
        if average_volume is None or average_volume <= _ZERO:
            return None
        return latest_volume / average_volume

    def _average_volume(self, bars: tuple[OHLCVBar, ...]) -> Decimal | None:
        if len(bars) < 20:
            return None
        lookback = bars[-21:-1] if len(bars) >= 21 else bars[-20:]
        if not lookback:
            return None
        return sum((bar.volume for bar in lookback), _ZERO) / Decimal(len(lookback))

    def _unavailable_reasons(
        self,
        *,
        bar_count: int,
        dma_20: Decimal | None,
        dma_50: Decimal | None,
        dma_200: Decimal | None,
        atr_14: Decimal | None,
        swing_high: Decimal | None,
        swing_low: Decimal | None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if dma_20 is None:
            reasons.append(f"20-DMA unavailable; requires 20 bars; has {bar_count}")
        if dma_50 is None:
            reasons.append(f"50-DMA unavailable; requires 50 bars; has {bar_count}")
        if dma_200 is None:
            reasons.append(f"200-DMA unavailable; requires 200 bars; has {bar_count}")
        if atr_14 is None:
            reasons.append(f"ATR(14) unavailable; requires 15 bars; has {bar_count}")
        if swing_high is None or swing_low is None:
            reasons.append(
                f"Swing levels unavailable; requires 2 bars; has {bar_count}"
            )
        if bar_count < 20:
            reasons.append(
                f"Relative volume unavailable; requires 20 bars; has {bar_count}"
            )
        return tuple(reasons)

    def _swing_high(self, bars: tuple[OHLCVBar, ...]) -> Decimal | None:
        if len(bars) < 2:
            return None
        lookback = bars[-min(len(bars), 60) :]
        return max(bar.high_price for bar in lookback)

    def _swing_low(self, bars: tuple[OHLCVBar, ...]) -> Decimal | None:
        if len(bars) < 2:
            return None
        lookback = bars[-min(len(bars), 60) :]
        return min(bar.low_price for bar in lookback)

    def _fibonacci(
        self,
        candidate: RecommendationCandidate,
        swing_low: Decimal | None,
        swing_high: Decimal | None,
    ) -> FibonacciRetracementLevels:
        if swing_low is None or swing_high is None or swing_high <= swing_low:
            return FibonacciRetracementLevels(
                level_236=None,
                level_382=candidate.fibonacci_382,
                level_500=candidate.fibonacci_500,
                level_618=candidate.fibonacci_618,
                level_786=candidate.fibonacci_786,
            )
        range_size = swing_high - swing_low
        return FibonacciRetracementLevels(
            level_236=swing_high - (range_size * Decimal("0.236")),
            level_382=candidate.fibonacci_382
            or swing_high - (range_size * Decimal("0.382")),
            level_500=candidate.fibonacci_500
            or swing_high - (range_size * Decimal("0.500")),
            level_618=candidate.fibonacci_618
            or swing_high - (range_size * Decimal("0.618")),
            level_786=candidate.fibonacci_786
            or swing_high - (range_size * Decimal("0.786")),
        )

    def _nearest_support(
        self,
        *,
        candidate: RecommendationCandidate,
        latest_close: Decimal | None,
        dma_20: Decimal | None,
        dma_50: Decimal | None,
        swing_low: Decimal | None,
        fibonacci: FibonacciRetracementLevels,
    ) -> tuple[Decimal | None, str]:
        candidates = (
            (candidate.support_level, "explicit support"),
            (dma_20, "20-DMA"),
            (dma_50, "50-DMA"),
            (fibonacci.level_382, "38.2% Fibonacci"),
            (fibonacci.level_500, "50.0% Fibonacci"),
            (fibonacci.level_618, "61.8% Fibonacci"),
            (swing_low, "recent swing low"),
        )
        valid = tuple(
            (level, name)
            for level, name in candidates
            if level is not None and (latest_close is None or level <= latest_close)
        )
        if not valid:
            return None, "unavailable"
        return max(valid, key=lambda item: item[0])

    def _nearest_resistance(
        self,
        *,
        candidate: RecommendationCandidate,
        latest_close: Decimal | None,
        swing_high: Decimal | None,
    ) -> Decimal | None:
        candidates = (
            candidate.resistance_level,
            candidate.recent_high,
            swing_high,
        )
        valid = tuple(
            level
            for level in candidates
            if level is not None and (latest_close is None or level >= latest_close)
        )
        if not valid:
            return None
        return min(valid)

    def _nearest_level(
        self,
        latest_close: Decimal | None,
        levels: tuple[Decimal, ...],
    ) -> Decimal | None:
        if latest_close is None or len(levels) == 0:
            return None
        support_levels = tuple(level for level in levels if level <= latest_close)
        if support_levels:
            return max(support_levels)
        return min(levels, key=lambda level: abs(level - latest_close))

    def _retracement_zone(
        self,
        latest_close: Decimal | None,
        swing_low: Decimal | None,
        swing_high: Decimal | None,
    ) -> str:
        if latest_close is None or swing_low is None or swing_high is None:
            return "unavailable"
        if swing_high <= swing_low:
            return "unavailable"
        retracement = (swing_high - latest_close) / (swing_high - swing_low)
        if retracement <= Decimal("0.382"):
            return "shallow bullish retracement"
        if retracement <= Decimal("0.500"):
            return "healthy retracement"
        if retracement <= Decimal("0.618"):
            return "deep but acceptable retracement"
        if retracement <= Decimal("0.786"):
            return "caution retracement"
        return "breakdown risk"

    def _is_breakout_setup(
        self,
        candidate: RecommendationCandidate,
        evidence_assessment: EvidenceAssessment,
        levels: TradePlanMarketLevels,
    ) -> bool:
        return (
            (candidate.setup_type == "BREAKOUT" or candidate.breakout_attempt)
            and evidence_assessment.price_evidence.breakout_state == "BREAKOUT"
            and evidence_assessment.volume_evidence.breakout_volume_confirmation
            >= Decimal("0.60")
            and levels.nearest_resistance is not None
        )

    def _is_retracement_setup(
        self,
        candidate: RecommendationCandidate,
        evidence_assessment: EvidenceAssessment,
        levels: TradePlanMarketLevels,
    ) -> bool:
        return (
            (
                candidate.setup_type in {"PULLBACK", "RETRACEMENT", "EMA_PULLBACK"}
                or not candidate.breakout_attempt
            )
            and (
                evidence_assessment.price_evidence.retracement_state == "HEALTHY"
                or candidate.retracement_score >= Decimal("0.70")
            )
            and evidence_assessment.price_volume.supports_buy
            and levels.nearest_support is not None
        )

    def _confirmation_trigger(
        self,
        candidate: RecommendationCandidate,
        levels: TradePlanMarketLevels,
    ) -> Decimal | None:
        triggers = tuple(
            level
            for level in (
                candidate.reversal_candle_high,
                candidate.prior_day_high,
                candidate.previous_high_price,
                levels.latest_high,
            )
            if level is not None
        )
        if not triggers:
            return None
        return max(triggers)

    def _add_atr(
        self,
        level: Decimal | None,
        atr: Decimal | None,
        multiplier: str,
    ) -> Decimal | None:
        if level is None:
            return None
        if atr is None:
            return level
        return level + (atr * Decimal(multiplier))

    def _stop_loss(
        self,
        *,
        candidate: RecommendationCandidate,
        entry_price: Decimal | None,
        levels: TradePlanMarketLevels,
        evidence_assessment: EvidenceAssessment,
    ) -> Decimal | None:
        if entry_price is None or levels.atr_14 is None:
            return None
        supports = tuple(
            level
            for level in (
                levels.nearest_support,
                levels.recent_swing_low,
                levels.dma_20,
                levels.dma_50,
                candidate.retracement_low,
                evidence_assessment.candle_pattern.stop_level,
            )
            if level is not None and level < entry_price
        )
        if not supports:
            return None
        support = min(supports)
        buffer = Decimal("1.5") if self._high_volatility(levels) else Decimal("1.0")
        stop = support - (levels.atr_14 * buffer)
        if stop < _ZERO:
            return _ZERO
        if stop >= entry_price:
            return None
        return stop

    def _high_volatility(self, levels: TradePlanMarketLevels) -> bool:
        return (
            levels.latest_close is not None
            and levels.atr_14 is not None
            and levels.latest_close > _ZERO
            and (levels.atr_14 / levels.latest_close) >= Decimal("0.04")
        )

    def _targets(
        self,
        *,
        entry_price: Decimal | None,
        initial_stop: Decimal | None,
        levels: TradePlanMarketLevels,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        if entry_price is None or initial_stop is None or initial_stop >= entry_price:
            return None, None, None, None
        risk = entry_price - initial_stop
        target_1 = entry_price + (risk * Decimal("2"))
        target_2 = entry_price + (risk * Decimal("3"))
        measured_move = (
            entry_price + (levels.recent_swing_high - levels.recent_swing_low)
            if levels.recent_swing_high is not None
            and levels.recent_swing_low is not None
            else None
        )
        atr_extension = (
            entry_price + (levels.atr_14 * Decimal("3"))
            if levels.atr_14 is not None
            else None
        )
        target_3 = max(
            target
            for target in (
                levels.recent_swing_high,
                measured_move,
                entry_price + (risk * Decimal("4")),
                atr_extension,
            )
            if target is not None and target > entry_price
        )
        return target_1, target_2, target_3, (target_1 - entry_price) / risk

    def _invalidation(
        self,
        levels: TradePlanMarketLevels,
    ) -> tuple[Decimal | None, str]:
        latest_close = levels.latest_close
        if (
            latest_close is not None
            and levels.fibonacci.level_786 is not None
            and latest_close < levels.fibonacci.level_786
        ):
            return (
                levels.fibonacci.level_786,
                "strong invalidation: close below 78.6% Fibonacci retracement",
            )
        if (
            latest_close is not None
            and levels.fibonacci.level_618 is not None
            and latest_close < levels.fibonacci.level_618
        ):
            return (
                levels.fibonacci.level_618,
                "close below 61.8% Fibonacci retracement invalidates the setup",
            )
        if levels.dma_20 is not None:
            return levels.dma_20, "close below 20-DMA invalidates the setup"
        if levels.nearest_support is not None:
            return levels.nearest_support, "close below support invalidates the setup"
        return None, "20-DMA invalidation unavailable due to insufficient price history"

    def _trailing_stop_strategy(self, atr: Decimal | None) -> str:
        if atr is None:
            return "ATR trailing stop unavailable due to insufficient price history."
        atr_multiple = (atr * Decimal("2")).normalize()
        return (
            "After entry, trail stop at 2 x ATR below the highest closing price. "
            f"Trail at 2 x ATR ({atr_multiple}) below the highest close after entry."
        )

    def _explanation(
        self,
        *,
        score: RecommendationScore,
        evidence_assessment: EvidenceAssessment,
        levels: TradePlanMarketLevels,
        entry_price: Decimal | None,
        entry_zone_low: Decimal | None,
        entry_zone_high: Decimal | None,
        initial_stop: Decimal | None,
        target_1: Decimal | None,
        target_2: Decimal | None,
        target_3: Decimal | None,
        invalidation_level: Decimal | None,
        invalidation_reason: str,
        trailing_stop_strategy: str,
    ) -> str:
        retracement_effect = "kept neutral because swing data is unavailable"
        if levels.retracement_zone != "unavailable":
            retracement_effect = (
                "improved"
                if score.breakdown.retracement_points >= Decimal("4")
                else "reduced"
                if score.breakdown.retracement_points < Decimal("3")
                else "kept neutral"
            )
        support_text = "Support used: unavailable. "
        if levels.nearest_support is not None:
            support_text = (
                f"Support used: {levels.nearest_support_name} at "
                f"{_money_text(levels.nearest_support)}. "
            )
        return (
            f"{score.decision.value} because the final score is {score.score}/100. "
            f"Price action is {evidence_assessment.price_evidence.structure_state} "
            f"with {evidence_assessment.price_evidence.breakout_state}. "
            f"Volume is scoring {evidence_assessment.volume_evidence.volume_score} "
            "as confirmation. "
            f"Candle pattern {evidence_assessment.candle_pattern.pattern} "
            f"{evidence_assessment.candle_pattern.confirmation.lower()} the setup. "
            f"Retracement {retracement_effect} the signal. "
            f"{support_text}"
            f"Entry zone: {_money_text(entry_zone_low)} to "
            f"{_money_text(entry_zone_high)}; confirmation entry: "
            f"{_money_text(entry_price)}. Stop loss: {_money_text(initial_stop)}. "
            f"Invalidation: {_money_text(invalidation_level)} "
            f"({invalidation_reason}). Targets: {_money_text(target_1)}, "
            f"{_money_text(target_2)}, {_money_text(target_3)}. "
            f"{_dma_20_invalidation_text(levels.dma_20)} {trailing_stop_strategy} "
            "Volume condition: breakout or bounce must confirm above average volume."
        )


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
            and candidate.current_price > candidate.previous_close
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
        if not _has_retracement_context(candidate):
            return Decimal("0.50")
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


class TradeSetupEngine:
    """Recognize professional trade setups from deterministic evidence."""

    _ALIASES: Mapping[str, str] = {
        "EMA_PULLBACK": "EMA PULLBACK",
        "PULLBACK": "EMA PULLBACK",
        "FIRST_PULLBACK": "FIRST PULLBACK AFTER BREAKOUT",
        "FIRST_PULLBACK_AFTER_BREAKOUT": "FIRST PULLBACK AFTER BREAKOUT",
        "BULL_FLAG": "BULL FLAG",
        "HIGH_TIGHT_FLAG": "HIGH TIGHT FLAG",
        "MOMENTUM_CONTINUATION": "MOMENTUM CONTINUATION",
        "VCP": "VOLATILITY CONTRACTION PATTERN",
        "VOLATILITY_CONTRACTION_PATTERN": "VOLATILITY CONTRACTION PATTERN",
        "DARVAS_BOX": "DARVAS BOX",
        "FLAT_BASE": "FLAT BASE",
        "CUP_HANDLE": "CUP & HANDLE",
        "CUP_AND_HANDLE": "CUP & HANDLE",
        "ASCENDING_TRIANGLE": "ASCENDING TRIANGLE",
        "RECTANGLE_BREAKOUT": "RECTANGLE BREAKOUT",
        "52_WEEK_HIGH": "52 WEEK HIGH BREAKOUT",
        "52_WEEK_HIGH_BREAKOUT": "52 WEEK HIGH BREAKOUT",
        "DOUBLE_BOTTOM": "DOUBLE BOTTOM",
        "ROUNDED_BOTTOM": "ROUNDED BOTTOM",
        "INVERSE_HEAD_SHOULDERS": "INVERSE HEAD & SHOULDERS",
        "FAILED_BREAKOUT": "FAILED BREAKOUT",
        "DISTRIBUTION": "DISTRIBUTION",
        "LOWER_HIGH_BREAKDOWN": "LOWER HIGH BREAKDOWN",
        "DESCENDING_TRIANGLE": "DESCENDING TRIANGLE",
        "TREND_FAILURE": "TREND FAILURE",
        "NO_SETUP": "NO VALID SETUP",
        "WEAK_RANDOM": "NO VALID SETUP",
        "RANDOM": "NO VALID SETUP",
        "WEAK": "NO VALID SETUP",
    }
    _CATEGORIES: Mapping[str, str] = {
        "EMA PULLBACK": "TREND CONTINUATION",
        "FIRST PULLBACK AFTER BREAKOUT": "TREND CONTINUATION",
        "BULL FLAG": "TREND CONTINUATION",
        "HIGH TIGHT FLAG": "TREND CONTINUATION",
        "MOMENTUM CONTINUATION": "TREND CONTINUATION",
        "VOLATILITY CONTRACTION PATTERN": "BREAKOUT",
        "DARVAS BOX": "BREAKOUT",
        "FLAT BASE": "BREAKOUT",
        "CUP & HANDLE": "BREAKOUT",
        "ASCENDING TRIANGLE": "BREAKOUT",
        "RECTANGLE BREAKOUT": "BREAKOUT",
        "52 WEEK HIGH BREAKOUT": "BREAKOUT",
        "DOUBLE BOTTOM": "REVERSAL",
        "ROUNDED BOTTOM": "REVERSAL",
        "INVERSE HEAD & SHOULDERS": "REVERSAL",
        "FAILED BREAKOUT": "BEARISH",
        "DISTRIBUTION": "BEARISH",
        "LOWER HIGH BREAKDOWN": "BEARISH",
        "DESCENDING TRIANGLE": "BEARISH",
        "TREND FAILURE": "BEARISH",
        "NO VALID SETUP": "NEUTRAL",
    }

    def __init__(
        self,
        *,
        trade_plan_engine: TradePlanIntelligenceEngine | None = None,
    ) -> None:
        self._trade_plan_engine = trade_plan_engine or TradePlanIntelligenceEngine()

    def assess(
        self,
        *,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
        evidence_assessment: EvidenceAssessment,
    ) -> TradeSetupAssessment:
        levels = self._trade_plan_engine.market_levels(candidate)
        setup_name = self._detect_setup(candidate, price_volume, candle_pattern)
        category = self._CATEGORIES[setup_name]
        confidence = self._confidence(
            candidate,
            price_volume,
            candle_pattern,
            evidence_assessment,
            category,
            setup_name,
        )
        quality = self._quality(confidence, category)
        stage = self._stage(candidate, price_volume, setup_name, category, quality)
        entry_ready, readiness_reason = self._entry_readiness(
            candidate,
            price_volume,
            candle_pattern,
            category,
            quality,
            stage,
            levels,
        )
        entries = self._entries(candidate, levels, setup_name)
        stage = self._normalized_stage(stage, entry_ready)
        exits = self._exits(
            candidate,
            entries["confirmation_entry"] or entries["preferred_entry"],
            levels,
        )
        holding_period = self._holding_period(setup_name)

        return TradeSetupAssessment(
            setup_name=setup_name,
            setup_category=category,
            setup_quality=quality,
            setup_confidence=confidence,
            setup_stage=stage,
            entry_ready=entry_ready,
            aggressive_entry=entries["aggressive_entry"],
            preferred_entry=entries["preferred_entry"],
            confirmation_entry=entries["confirmation_entry"],
            maximum_chase_price=entries["maximum_chase_price"],
            stop_chase_price=entries["stop_chase_price"],
            initial_stop=exits["initial_stop"],
            move_stop_to_breakeven=exits["move_stop_to_breakeven"],
            partial_exit=exits["partial_exit"],
            atr_trail=self._atr_trail(levels),
            final_exit=exits["final_exit"],
            expected_holding_period=holding_period[0],
            minimum_holding_period=holding_period[1],
            maximum_holding_period=holding_period[2],
            holding_period_basis=holding_period[3],
            rationale=self._rationale(
                setup_name,
                category,
                price_volume,
                candle_pattern,
            ),
            readiness_reason=readiness_reason,
        )

    def apply_decision_rules(
        self,
        score: RecommendationScore,
        setup: TradeSetupAssessment,
    ) -> RecommendationScore:
        adjusted_score = score.score
        if setup.setup_category == "BEARISH":
            if setup.setup_name == "FAILED BREAKOUT":
                adjusted_score = min(adjusted_score, Decimal("40"))
            else:
                adjusted_score = min(adjusted_score, Decimal("39"))
        elif setup.setup_name == "NO VALID SETUP" or setup.setup_quality == "REJECT":
            adjusted_score = min(adjusted_score, Decimal("59"))
        elif adjusted_score >= Decimal("75") and not setup.entry_ready:
            adjusted_score = Decimal("74")

        decision = self._decision(adjusted_score, setup)
        if adjusted_score == score.score and decision is score.decision:
            return score
        return replace(
            score,
            score=adjusted_score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            decision=decision,
        )

    def _detect_setup(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
    ) -> str:
        hinted = self._hinted_setup(candidate)
        if hinted in self._CATEGORIES and hinted != "NO VALID SETUP":
            if self._CATEGORIES[hinted] == "BEARISH":
                return hinted
            if self._hard_bearish_setup(candidate, price_volume, candle_pattern):
                return self._hard_bearish_name(candidate, price_volume)
            return hinted
        if hinted == "NO VALID SETUP" and candidate.setup_type is not None:
            if self._hard_bearish_setup(candidate, price_volume, candle_pattern):
                return self._hard_bearish_name(candidate, price_volume)
            return hinted
        if self._hard_bearish_setup(candidate, price_volume, candle_pattern):
            return self._hard_bearish_name(candidate, price_volume)
        if self._is_bull_flag(candidate, price_volume):
            return "BULL FLAG"
        if self._is_ema_pullback(candidate, price_volume):
            return "EMA PULLBACK"
        if self._is_vcp(candidate, price_volume):
            return "VOLATILITY CONTRACTION PATTERN"
        if self._is_momentum_continuation(candidate, price_volume):
            return "MOMENTUM CONTINUATION"
        if candidate.retracement_score >= Decimal("0.75"):
            return "EMA PULLBACK"
        if (candidate.breakout_setup_score or candidate.strategy_score) >= Decimal(
            "0.50"
        ):
            return "MOMENTUM CONTINUATION"
        return "NO VALID SETUP"

    def _hinted_setup(self, candidate: RecommendationCandidate) -> str:
        if candidate.setup_type is None:
            return "NO VALID SETUP"
        key = candidate.setup_type.strip().upper().replace("-", "_").replace(" ", "_")
        return self._ALIASES.get(key, key.replace("_", " "))

    def _hard_bearish_setup(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
    ) -> bool:
        return (
            price_volume.supports_sell
            or candidate.lower_highs_lower_lows
            or (
                candidate.breakout_attempt
                and candidate.resistance_level is not None
                and _is_below(candidate.current_price, candidate.resistance_level)
                and candle_pattern.confirmation == "CONFLICTS"
            )
            or (
                candidate.dma_50 is not None
                and _is_below(candidate.current_price, candidate.dma_50)
                and _volume_ratio(candidate) >= Decimal("1.50")
            )
        )

    def _hard_bearish_name(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> str:
        if candidate.breakout_attempt and not price_volume.supports_sell:
            return "FAILED BREAKOUT"
        if candidate.lower_highs_lower_lows:
            return "LOWER HIGH BREAKDOWN"
        if price_volume.volume_evidence.distribution_score >= Decimal("0.70"):
            return "DISTRIBUTION"
        return "TREND FAILURE"

    def _is_bull_flag(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> bool:
        return (
            candidate.higher_highs_higher_lows
            and price_volume.price_evidence.trend_state in {"UPTREND", "STRONG_UPTREND"}
            and price_volume.price_evidence.retracement_state in {"HEALTHY", "NEUTRAL"}
            and price_volume.volume_evidence.volume_dry_up_score >= Decimal("0.55")
            and candidate.retracement_score >= Decimal("0.60")
        )

    def _is_ema_pullback(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> bool:
        near_ema = _near_any_level(
            candidate.current_price,
            (candidate.dma_20, candidate.ema_20, candidate.dma_50, candidate.ema_50),
            candidate.atr,
        )
        return (
            near_ema
            and price_volume.price_evidence.trend_state in {"UPTREND", "STRONG_UPTREND"}
            and price_volume.price_evidence.retracement_state == "HEALTHY"
        )

    def _is_vcp(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> bool:
        return (
            candidate.resistance_level is not None
            and candidate.current_price is not None
            and candidate.current_price <= candidate.resistance_level
            and price_volume.price_evidence.volatility_state == "CONTROLLED"
            and price_volume.volume_evidence.volume_dry_up_score >= Decimal("0.60")
            and price_volume.price_evidence.price_score >= Decimal("0.55")
        )

    def _is_momentum_continuation(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
    ) -> bool:
        return (
            candidate.breakout_attempt
            and price_volume.supports_buy
            and price_volume.price_evidence.trend_state == "STRONG_UPTREND"
        )

    def _confidence(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
        evidence_assessment: EvidenceAssessment,
        category: str,
        setup_name: str,
    ) -> Decimal:
        if setup_name == "NO VALID SETUP":
            return Decimal("30.00")
        if category == "BEARISH":
            bearish_score = max(
                price_volume.volume_evidence.distribution_score,
                price_volume.volume_evidence.selloff_volume_penalty,
                Decimal("0.70") if candidate.lower_highs_lower_lows else Decimal("0"),
            )
            return _points(bearish_score)
        weighted = (
            self._trend_component(price_volume) * Decimal("0.17")
            + price_volume.price_evidence.price_score * Decimal("0.18")
            + price_volume.volume_evidence.volume_score * Decimal("0.16")
            + candidate.retracement_score * Decimal("0.11")
            + self._market_component(candidate) * Decimal("0.10")
            + (candidate.sector_strength_score or candidate.market_intelligence_score)
            * Decimal("0.08")
            + (
                candidate.benchmark_relative_strength
                or candidate.relative_strength_score
                or candidate.probability_score
            )
            * Decimal("0.10")
            + candle_pattern.score * Decimal("0.06")
            + candidate.risk_score * Decimal("0.04")
        )
        if category == "BREAKOUT":
            weighted = _bounded_ratio(
                weighted * Decimal("0.85")
                + price_volume.volume_evidence.breakout_volume_confirmation
                * Decimal("0.15")
            )
        if category == "REVERSAL":
            weighted = _bounded_ratio(
                weighted * Decimal("0.85") + candle_pattern.score * Decimal("0.15")
            )
        if evidence_assessment.conflict_penalty_points > _ZERO:
            weighted -= min(
                evidence_assessment.conflict_penalty_points / _HUNDRED,
                Decimal("0.10"),
            )
        return _points(_bounded_ratio(weighted))

    def _quality(self, confidence: Decimal, category: str) -> str:
        if category == "BEARISH":
            return "REJECT"
        if confidence >= Decimal("90"):
            return "A+"
        if confidence >= Decimal("80"):
            return "A"
        if confidence >= Decimal("68"):
            return "B"
        if confidence >= Decimal("50"):
            return "C"
        return "REJECT"

    def _stage(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        setup_name: str,
        category: str,
        quality: str,
    ) -> str:
        if category == "BEARISH" or quality == "REJECT":
            return "INVALID"
        if setup_name == "NO VALID SETUP":
            return "INVALID"
        if candidate.current_price is None:
            return "BUILDING"
        if _is_late_setup(candidate):
            return "LATE"
        if candidate.resistance_level is not None:
            if candidate.current_price > candidate.resistance_level:
                return "ENTRY_READY"
            if _within_percent(
                candidate.current_price,
                candidate.resistance_level,
                "2",
            ):
                return "READY_FOR_CONFIRMATION"
        if price_volume.price_evidence.breakout_state == "BREAKOUT":
            return "ENTRY_READY"
        if price_volume.price_evidence.retracement_state == "HEALTHY":
            if (
                setup_name in {"EMA PULLBACK", "BULL FLAG"}
                and price_volume.supports_buy
            ):
                return "ENTRY_READY"
            return "READY_FOR_CONFIRMATION"
        return "BUILDING"

    def _entry_readiness(
        self,
        candidate: RecommendationCandidate,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
        category: str,
        quality: str,
        stage: str,
        levels: TradePlanMarketLevels,
    ) -> tuple[bool, str]:
        if category == "BEARISH":
            return False, "Bearish setup is not eligible for a long entry."
        if quality in {"C", "REJECT"}:
            return False, "Setup quality is below the deployment threshold."
        if stage in {"BUILDING", "READY_FOR_CONFIRMATION"}:
            return False, "Setup is not ready; wait for price confirmation."
        if stage == "LATE":
            return False, "Setup is late; avoid fresh deployment."
        if stage != "ENTRY_READY" and stage != "ACTIVE":
            return False, "Setup lifecycle is not entry-ready."
        if levels.nearest_resistance is None and levels.nearest_support is None:
            return False, "Entry cannot be validated without support or resistance."
        if candle_pattern.confirmation == "CONFLICTS":
            return False, "Candle pattern conflicts with the setup."
        if not price_volume.supports_buy:
            return False, "Price-volume confirmation is not strong enough for BUY."
        return True, "Setup is ready with price-volume confirmation."

    def _entries(
        self,
        candidate: RecommendationCandidate,
        levels: TradePlanMarketLevels,
        setup_name: str,
    ) -> Mapping[str, Decimal | None]:
        latest = levels.latest_close or candidate.current_price
        support = levels.nearest_support
        resistance = levels.nearest_resistance or candidate.resistance_level
        atr = levels.atr_14 or candidate.atr
        confirmation = max(
            tuple(
                value
                for value in (
                    candidate.prior_day_high,
                    candidate.reversal_candle_high,
                    resistance,
                    latest,
                )
                if value is not None
            ),
            default=None,
        )
        is_pullback = setup_name in {"EMA PULLBACK", "BULL FLAG"}
        preferred = (
            self._add_atr(support, atr, "0.50")
            if is_pullback
            else self._add_atr(resistance, atr, "0.50")
        )
        if preferred is None:
            preferred = latest
        aggressive = (support if is_pullback else resistance) or latest
        maximum_chase = self._add_atr(confirmation or preferred, atr, "0.50")
        stop_chase = self._add_atr(confirmation or preferred, atr, "1.00")
        return {
            "aggressive_entry": _money_optional(aggressive),
            "preferred_entry": _money_optional(preferred),
            "confirmation_entry": _money_optional(confirmation),
            "maximum_chase_price": _money_optional(maximum_chase),
            "stop_chase_price": _money_optional(stop_chase),
        }

    def _exits(
        self,
        candidate: RecommendationCandidate,
        preferred_entry: Decimal | None,
        levels: TradePlanMarketLevels,
    ) -> Mapping[str, Decimal | None]:
        entry = preferred_entry
        atr = levels.atr_14
        support = levels.nearest_support
        if entry is None:
            return {
                "initial_stop": None,
                "move_stop_to_breakeven": None,
                "partial_exit": None,
                "final_exit": None,
            }
        structural_candidates = tuple(
            value
            for value in (
                support,
                levels.recent_swing_low,
                levels.dma_20,
                levels.dma_50,
                candidate.retracement_low,
            )
            if value is not None and _ZERO < value < entry
        )
        support_anchor = max(structural_candidates) if structural_candidates else None
        stop_candidates = tuple(
            value
            for value in (
                self._subtract_atr(support_anchor, atr, "0.50"),
                self._subtract_atr(support_anchor, atr, "0.25"),
                self._subtract_atr(entry, atr, "1.50"),
            )
            if (
                value is not None
                and _ZERO < value < entry
                and (support_anchor is None or value < support_anchor)
            )
        )
        initial_stop = max(stop_candidates) if stop_candidates else None
        risk = entry - initial_stop if initial_stop is not None else None
        partial_exit = entry + risk * Decimal("2") if risk is not None else None
        final_exit = entry + risk * Decimal("3") if risk is not None else None
        move_stop = entry + risk if risk is not None else None
        return {
            "initial_stop": _money_optional(initial_stop),
            "move_stop_to_breakeven": _money_optional(move_stop),
            "partial_exit": _money_optional(partial_exit),
            "final_exit": _money_optional(final_exit),
        }

    def _atr_trail(self, levels: TradePlanMarketLevels) -> str:
        if levels.atr_14 is None:
            return "ATR trail unavailable until ATR is available."
        return (
            "After entry, trail stop at 2 x ATR below the highest closing price "
            f"(ATR {levels.atr_14})."
        )

    def _normalized_stage(self, stage: str, entry_ready: bool) -> str:
        if stage in {"INVALID", "LATE"}:
            return stage
        if entry_ready:
            return "ENTRY_READY"
        if stage in {"ENTRY_READY", "ACTIVE"}:
            return "READY_FOR_CONFIRMATION"
        return stage

    def _holding_period(
        self,
        setup_name: str,
    ) -> tuple[str, int | None, int | None, str]:
        mapping: Mapping[str, tuple[str, int | None, int | None, str]] = {
            "MOMENTUM CONTINUATION": (
                "5-15 trading days",
                5,
                15,
                "Momentum Continuation setup behavior",
            ),
            "EMA PULLBACK": (
                "7-20 trading days",
                7,
                20,
                "EMA Pullback setup behavior",
            ),
            "BULL FLAG": (
                "5-12 trading days",
                5,
                12,
                "Bull Flag setup behavior",
            ),
            "VOLATILITY CONTRACTION PATTERN": (
                "10-30 trading days",
                10,
                30,
                "VCP Breakout setup behavior",
            ),
            "FLAT BASE": (
                "15-45 trading days",
                15,
                45,
                "Flat Base Breakout setup behavior",
            ),
            "CUP & HANDLE": (
                "20-60 trading days",
                20,
                60,
                "Cup & Handle setup behavior",
            ),
            "DARVAS BOX": (
                "10-30 trading days",
                10,
                30,
                "Darvas Box setup behavior",
            ),
            "FAILED BREAKOUT": (
                "exit / avoid immediately",
                None,
                None,
                "Failed Breakout risk behavior",
            ),
            "TREND FAILURE": (
                "exit / avoid immediately",
                None,
                None,
                "Trend Failure risk behavior",
            ),
            "NO VALID SETUP": (
                "unavailable",
                None,
                None,
                "No valid setup",
            ),
        }
        return mapping.get(
            setup_name,
            (
                "unavailable",
                None,
                None,
                "Setup-specific holding period unavailable",
            ),
        )

    def _rationale(
        self,
        setup_name: str,
        category: str,
        price_volume: PriceVolumeAssessment,
        candle_pattern: CandlePatternAssessment,
    ) -> str:
        return (
            f"{setup_name} classified as {category}: "
            f"price is {price_volume.price_evidence.trend_state}/"
            f"{price_volume.price_evidence.structure_state}, volume score is "
            f"{price_volume.volume_evidence.volume_score}, and candle confirmation is "
            f"{candle_pattern.confirmation}."
        )

    def _trend_component(self, price_volume: PriceVolumeAssessment) -> Decimal:
        if price_volume.price_evidence.trend_state == "STRONG_UPTREND":
            return Decimal("0.90")
        if price_volume.price_evidence.trend_state == "UPTREND":
            return Decimal("0.75")
        if price_volume.price_evidence.trend_state == "DOWNTREND":
            return Decimal("0.20")
        return Decimal("0.50")

    def _market_component(self, candidate: RecommendationCandidate) -> Decimal:
        if candidate.market_regime == "BULL":
            return max(
                candidate.market_regime_score or candidate.market_intelligence_score,
                Decimal("0.70"),
            )
        if candidate.market_regime == "BEAR":
            return min(
                candidate.market_regime_score or candidate.market_intelligence_score,
                Decimal("0.30"),
            )
        return min(
            candidate.market_regime_score or candidate.market_intelligence_score,
            Decimal("0.60"),
        )

    def _add_atr(
        self,
        value: Decimal | None,
        atr: Decimal | None,
        multiplier: str,
    ) -> Decimal | None:
        if value is None:
            return None
        if atr is None:
            return value
        return value + atr * Decimal(multiplier)

    def _subtract_atr(
        self,
        value: Decimal | None,
        atr: Decimal | None,
        multiplier: str,
    ) -> Decimal | None:
        if value is None:
            return None
        if atr is None:
            return value
        return value - atr * Decimal(multiplier)

    def _decision(
        self,
        adjusted_score: Decimal,
        setup: TradeSetupAssessment,
    ) -> RecommendationDecision:
        if setup.setup_name == "FAILED BREAKOUT":
            return RecommendationDecision.AVOID
        if setup.setup_name in {
            "DISTRIBUTION",
            "LOWER HIGH BREAKDOWN",
            "TREND FAILURE",
            "DESCENDING TRIANGLE",
        } or adjusted_score < Decimal("40"):
            return RecommendationDecision.SELL
        if setup.setup_category == "BEARISH":
            return RecommendationDecision.AVOID
        if adjusted_score < Decimal("60"):
            return RecommendationDecision.AVOID
        if adjusted_score < Decimal("75") or not setup.entry_ready:
            return RecommendationDecision.WATCHLIST
        if adjusted_score >= Decimal("90"):
            return RecommendationDecision.STRONG_BUY
        return RecommendationDecision.BUY


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
        if not _has_retracement_context(candidate):
            return Decimal("0.50")
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
        hard_risk_reason = _hard_risk_candle_reason(
            candidate,
            price_volume,
            candle_pattern,
        )
        if hard_risk_reason is not None:
            score = min(score, Decimal("59"))
            if price_volume.supports_sell:
                score = min(score, Decimal("39"))
        elif candle_pattern.confirmation == "CONFLICTS":
            if score >= Decimal("75"):
                score = min(score, Decimal("74"))
            elif score >= Decimal("60"):
                score = max(score - Decimal("4"), Decimal("60"))
            else:
                score = max(score - Decimal("3"), Decimal("40"))
        if score >= Decimal("75") and not _has_minimum_trade_plan_context(candidate):
            score = Decimal("74")
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
        trade_plan_engine: TradePlanIntelligenceEngine | None = None,
        trade_setup_engine: TradeSetupEngine | None = None,
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
        self._trade_plan_engine = trade_plan_engine or TradePlanIntelligenceEngine()
        self._trade_setup_engine = trade_setup_engine or TradeSetupEngine(
            trade_plan_engine=self._trade_plan_engine,
        )

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
        candidate = _candidate_with_latest_ohlcv(candidate)
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
        trade_setup = self._trade_setup_engine.assess(
            candidate=candidate,
            price_volume=price_volume,
            candle_pattern=candle_pattern,
            evidence_assessment=evidence_assessment,
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
        score = self._trade_setup_engine.apply_decision_rules(score, trade_setup)
        trade_plan = self._trade_plan(
            candidate=candidate,
            score=score,
            evidence_assessment=evidence_assessment,
            trade_setup=trade_setup,
        )
        if score.is_actionable and not _has_valid_trade_plan(trade_plan):
            score = replace(
                score,
                score=Decimal("74.00"),
                decision=RecommendationDecision.WATCHLIST,
            )
            trade_plan = self._trade_plan(
                candidate=candidate,
                score=score,
                evidence_assessment=evidence_assessment,
                trade_setup=trade_setup,
            )
        action = self._action_for(score.decision)
        trade_strategies = _trade_strategy_playbooks(
            trade_plan=trade_plan,
            score=score,
            trade_setup=trade_setup,
            price_history=candidate.price_history,
        )
        metadata = dict(candidate.metadata)
        metadata.update(
            recommendation_historical_edge_metadata(
                setup_name=trade_setup.setup_name,
                market_regime=candidate.market_regime,
            )
        )
        if metadata.get("historical_setup_edge") == "computed":
            score = _apply_historical_edge_adjustment(score, metadata)
            trade_plan = self._trade_plan(
                candidate=candidate,
                score=score,
                evidence_assessment=evidence_assessment,
                trade_setup=trade_setup,
            )
        if candidate.current_price is not None:
            metadata["current_price"] = str(_money(candidate.current_price))
            metadata["price"] = str(_money(candidate.current_price))

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
                trade_setup=trade_setup,
            ),
            trade_plan=trade_plan,
            evidence_assessment=evidence_assessment,
            trade_setup=trade_setup,
            trade_strategies=trade_strategies,
            metadata=metadata,
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
        trade_setup: TradeSetupAssessment,
    ) -> RecommendationTradePlan:
        levels = self._trade_plan_engine.assess(
            candidate=candidate,
            score=score,
            evidence_assessment=evidence_assessment,
        )
        confidence = _confidence(score.score)
        entry_zone_low = trade_setup.aggressive_entry or levels.entry_zone_low
        entry_zone_high = trade_setup.preferred_entry or levels.entry_zone_high
        entry_price = trade_setup.confirmation_entry or levels.entry_price
        initial_stop = trade_setup.initial_stop or levels.initial_stop_loss
        target_1 = trade_setup.partial_exit or levels.target_1
        target_2 = trade_setup.final_exit or levels.target_2
        target_3 = _setup_target_3(
            entry_price=entry_price,
            initial_stop=initial_stop,
            atr_value=levels.market_levels.atr_14,
            fallback=levels.target_3,
        )
        risk_reward_ratio = _risk_reward_ratio(
            entry_price=entry_price,
            initial_stop=initial_stop,
            target=target_1,
            fallback=levels.risk_reward_ratio,
        )
        trade_plan_explanation = _setup_trade_plan_explanation(
            trade_setup=trade_setup,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            entry_price=entry_price,
            initial_stop=initial_stop,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            fallback=levels.trade_plan_explanation,
        )
        entry_trigger_style = _entry_trigger_style(
            trade_setup=trade_setup,
            evidence_assessment=evidence_assessment,
        )

        return RecommendationTradePlan(
            final_signal=score.decision.value,
            final_score=score.score,
            confidence=confidence,
            entry_price=entry_price,
            entry_trigger_style=entry_trigger_style,
            trigger_status=_trigger_status(
                trade_setup=trade_setup,
                score=score,
                entry_trigger_style=entry_trigger_style,
            ),
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            initial_stop_loss=initial_stop,
            trailing_stop_strategy=levels.trailing_stop_strategy,
            target_1=target_1,
            target_2=target_2,
            target_3=target_3,
            risk_reward_ratio=risk_reward_ratio,
            invalidation_level=levels.invalidation_level,
            invalidation_reason=levels.invalidation_reason,
            retracement_score=candidate.retracement_score,
            retracement_weight=score.breakdown.retracement_weight,
            retracement_zone=levels.market_levels.nearest_support_name,
            nearest_fibonacci_level=levels.market_levels.nearest_fibonacci_level,
            swing_high=levels.market_levels.recent_swing_high,
            swing_low=levels.market_levels.recent_swing_low,
            support_level_used=levels.market_levels.nearest_support,
            atr_value=levels.market_levels.atr_14,
            dma_20_invalidation=levels.market_levels.dma_20,
            dma_50=levels.market_levels.dma_50,
            dma_200=levels.market_levels.dma_200,
            relative_volume=levels.market_levels.relative_volume,
            historical_bar_count=levels.market_levels.historical_bar_count,
            unavailable_reasons=levels.market_levels.unavailable_reasons,
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
            setup_name=trade_setup.setup_name,
            setup_category=trade_setup.setup_category,
            setup_quality_label=trade_setup.setup_quality,
            setup_confidence=trade_setup.setup_confidence,
            setup_stage=trade_setup.setup_stage,
            setup_entry_ready=trade_setup.entry_ready,
            aggressive_entry=trade_setup.aggressive_entry,
            preferred_entry=trade_setup.preferred_entry,
            confirmation_entry=trade_setup.confirmation_entry,
            maximum_chase_price=trade_setup.maximum_chase_price,
            stop_chase_price=trade_setup.stop_chase_price,
            move_stop_to_breakeven=trade_setup.move_stop_to_breakeven,
            partial_exit=trade_setup.partial_exit,
            atr_trail=trade_setup.atr_trail,
            final_exit=trade_setup.final_exit,
            setup_expectancy_status=trade_setup.expectancy_status,
            expected_holding_period=trade_setup.expected_holding_period,
            minimum_holding_period=trade_setup.minimum_holding_period,
            maximum_holding_period=trade_setup.maximum_holding_period,
            holding_period_basis=trade_setup.holding_period_basis,
            setup_rationale=trade_setup.rationale,
            setup_readiness_reason=trade_setup.readiness_reason,
            trade_plan_explanation=trade_plan_explanation,
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
        trade_setup: TradeSetupAssessment,
    ) -> tuple[str, ...]:
        lines = [
            f"{candidate.symbol}: {score.decision.value}",
            f"Detected Setup: {trade_setup.setup_name}",
            f"Setup Category: {trade_setup.setup_category}",
            (
                "Setup Quality: "
                f"{trade_setup.setup_quality} "
                f"({trade_setup.setup_confidence}% confidence)"
            ),
            f"Setup Stage: {trade_setup.setup_stage}",
            f"Entry Ready: {trade_setup.entry_ready}",
            f"Why Alpha believes this setup exists: {trade_setup.rationale}",
            f"What must happen before BUY: {trade_setup.readiness_reason}",
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
            f"Historical bars: {trade_plan.historical_bar_count}",
            f"Support level used: {_money_text(trade_plan.support_level_used)}",
            (
                "Entry zone: "
                f"{_money_text(trade_plan.entry_zone_low)} to "
                f"{_money_text(trade_plan.entry_zone_high)}"
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

        hard_risk_reason = _hard_risk_candle_reason(
            candidate,
            evidence_assessment.price_volume,
            evidence_assessment.candle_pattern,
        )
        if hard_risk_reason is not None:
            lines.insert(8, f"Hard-risk override: {hard_risk_reason}.")
        if (
            score.decision is RecommendationDecision.WATCHLIST
            and trade_setup.setup_quality in {"A+", "A", "B"}
            and not trade_setup.entry_ready
        ):
            lines.insert(
                8,
                (f"Why BUY became WATCHLIST: {trade_setup.readiness_reason}"),
            )
        if trade_plan.unavailable_reasons:
            lines.extend(
                f"Unavailable: {reason}" for reason in trade_plan.unavailable_reasons
            )

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


def _points(value: Decimal) -> Decimal:
    return (value * _HUNDRED).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _entry_trigger_style(
    *,
    trade_setup: TradeSetupAssessment,
    evidence_assessment: EvidenceAssessment,
) -> EntryTriggerStyle:
    if trade_setup.setup_name in {"EMA PULLBACK"}:
        return EntryTriggerStyle.PULLBACK_TO_LEVEL
    if trade_setup.setup_name in {"BULL FLAG"}:
        return EntryTriggerStyle.RETEST_HOLD
    if (
        trade_setup.setup_category == "BREAKOUT"
        and evidence_assessment.volume_evidence.breakout_volume_confirmation
        >= Decimal("0.80")
    ):
        return EntryTriggerStyle.BREAKOUT_WITH_VOLUME
    if trade_setup.confirmation_entry is not None:
        return EntryTriggerStyle.CLOSE_ABOVE
    if trade_setup.preferred_entry is not None:
        return EntryTriggerStyle.ENTER_IN_ZONE
    return EntryTriggerStyle.CLOSE_ABOVE


def _trigger_status(
    *,
    trade_setup: TradeSetupAssessment,
    score: RecommendationScore,
    entry_trigger_style: EntryTriggerStyle,
) -> TriggerStatus:
    if (
        score.decision
        in {
            RecommendationDecision.AVOID,
            RecommendationDecision.SELL,
        }
        or trade_setup.setup_stage == "INVALID"
        or trade_setup.setup_quality == "REJECT"
    ):
        return TriggerStatus.INVALID_OR_NOT_ACTIONABLE
    if trade_setup.entry_ready and trade_setup.setup_stage in {"ENTRY_READY", "ACTIVE"}:
        return TriggerStatus.TRIGGER_CONFIRMED
    if entry_trigger_style is EntryTriggerStyle.BREAKOUT_WITH_VOLUME:
        return TriggerStatus.WAITING_FOR_VOLUME_CONFIRMATION
    if entry_trigger_style is EntryTriggerStyle.CROSS_ABOVE:
        return TriggerStatus.WAITING_FOR_CROSS_ABOVE
    return TriggerStatus.WAITING_FOR_CLOSE_ABOVE


def _setup_target_3(
    *,
    entry_price: Decimal | None,
    initial_stop: Decimal | None,
    atr_value: Decimal | None,
    fallback: Decimal | None,
) -> Decimal | None:
    if entry_price is None or initial_stop is None or initial_stop >= entry_price:
        return fallback
    risk = entry_price - initial_stop
    four_r = entry_price + risk * Decimal("4")
    atr_extension = (
        entry_price + atr_value * Decimal("3")
        if atr_value is not None and atr_value > _ZERO
        else None
    )
    target = max(
        value for value in (four_r, atr_extension, fallback) if value is not None
    )
    return _money_optional(target)


def _risk_reward_ratio(
    *,
    entry_price: Decimal | None,
    initial_stop: Decimal | None,
    target: Decimal | None,
    fallback: Decimal | None,
) -> Decimal | None:
    if (
        entry_price is None
        or initial_stop is None
        or target is None
        or initial_stop >= entry_price
    ):
        return fallback
    risk = entry_price - initial_stop
    reward = target - entry_price
    if risk <= _ZERO or reward <= _ZERO:
        return fallback
    return _quantize(reward / risk)


def _setup_trade_plan_explanation(
    *,
    trade_setup: TradeSetupAssessment,
    entry_zone_low: Decimal | None,
    entry_zone_high: Decimal | None,
    entry_price: Decimal | None,
    initial_stop: Decimal | None,
    target_1: Decimal | None,
    target_2: Decimal | None,
    target_3: Decimal | None,
    fallback: str,
) -> str:
    if (
        entry_zone_low is None
        or entry_zone_high is None
        or entry_price is None
        or initial_stop is None
    ):
        return fallback
    return (
        f"Detected {trade_setup.setup_name}, stage {trade_setup.setup_stage}. "
        f"Preferred entry is {_money_text(entry_zone_low)}-"
        f"{_money_text(entry_zone_high)} with confirmation above "
        f"{_money_text(entry_price)}. Initial stop is {_money_text(initial_stop)}. "
        f"Targets are {_money_text(target_1)}, {_money_text(target_2)}, "
        f"{_money_text(target_3)}. Current recommendation is driven by setup "
        f"readiness: {trade_setup.readiness_reason} {fallback}"
    )


class StatisticalEdgeEngine:
    def assess(
        self,
        *,
        trade_plan: RecommendationTradePlan,
        strategy_type: TradeStrategyType,
        action: TradeStrategyAction,
        price_history: tuple[OHLCVBar, ...] = (),
    ) -> StrategyEdgeStats:
        fill_probability = _fill_probability(strategy_type, action)
        fill_window_days = _fill_window_days(strategy_type, action)
        outcomes = SetupOutcomeSimulator().simulate(
            bars=HistoricalSetupMatcher().match(price_history),
            trade_plan=trade_plan,
            max_holding_period=trade_plan.maximum_holding_period or 20,
        )
        sample_size = len(outcomes)
        confidence = _edge_confidence(sample_size)
        if sample_size < 30:
            return StrategyEdgeStats(
                sample_size=sample_size,
                target_1_hit_rate=None,
                target_2_hit_rate=None,
                target_3_hit_rate=None,
                stop_loss_hit_rate=None,
                average_return=None,
                median_return=None,
                average_drawdown=None,
                median_holding_period_days=None,
                expectancy=None,
                fill_probability=fill_probability,
                fill_window_days=fill_window_days,
                confidence=confidence,
            )
        returns = tuple(outcome.return_ratio for outcome in outcomes)
        drawdowns = tuple(outcome.max_drawdown for outcome in outcomes)
        holding_periods = tuple(outcome.holding_period_days for outcome in outcomes)
        return StrategyEdgeStats(
            sample_size=sample_size,
            target_1_hit_rate=_hit_rate(outcome.target_1_hit for outcome in outcomes),
            target_2_hit_rate=_hit_rate(outcome.target_2_hit for outcome in outcomes),
            target_3_hit_rate=_hit_rate(outcome.target_3_hit for outcome in outcomes),
            stop_loss_hit_rate=_hit_rate(outcome.stop_loss_hit for outcome in outcomes),
            average_return=_average(returns),
            median_return=_median(returns),
            average_drawdown=_average(drawdowns),
            median_holding_period_days=int(_median_int(holding_periods)),
            expectancy=_average(returns),
            fill_probability=fill_probability,
            fill_window_days=fill_window_days,
            confidence=confidence,
        )


class HistoricalSetupMatcher:
    def match(self, bars: tuple[OHLCVBar, ...]) -> tuple[OHLCVBar, ...]:
        if len(bars) < 60:
            return ()
        matches: list[OHLCVBar] = []
        for index in range(50, len(bars) - 20):
            close = bars[index].close_price
            dma_20 = _simple_average(
                tuple(bar.close_price for bar in bars[index - 20 : index])
            )
            dma_50 = _simple_average(
                tuple(bar.close_price for bar in bars[index - 50 : index])
            )
            average_volume = _simple_average(
                tuple(bar.volume for bar in bars[index - 20 : index])
            )
            if (
                dma_20 is not None
                and dma_50 is not None
                and average_volume is not None
                and close >= dma_20
                and close >= dma_50
                and bars[index].volume >= average_volume * Decimal("0.80")
            ):
                matches.append(bars[index])
        return tuple(matches)


@dataclass(frozen=True, slots=True)
class SetupOutcome:
    target_1_hit: bool
    target_2_hit: bool
    target_3_hit: bool
    stop_loss_hit: bool
    max_drawdown: Decimal
    holding_period_days: int
    return_ratio: Decimal


class SetupOutcomeSimulator:
    def simulate(
        self,
        *,
        bars: tuple[OHLCVBar, ...],
        trade_plan: RecommendationTradePlan,
        max_holding_period: int,
    ) -> tuple[SetupOutcome, ...]:
        if (
            trade_plan.entry_price is None
            or trade_plan.initial_stop_loss is None
            or trade_plan.target_1 is None
        ):
            return ()
        risk_ratio = _relative_level(
            trade_plan.initial_stop_loss,
            trade_plan.entry_price,
        )
        target_1_ratio = _relative_level(trade_plan.target_1, trade_plan.entry_price)
        if risk_ratio is None or target_1_ratio is None:
            return ()
        target_2_ratio = _relative_level(trade_plan.target_2, trade_plan.entry_price)
        target_3_ratio = _relative_level(trade_plan.target_3, trade_plan.entry_price)
        outcomes: list[SetupOutcome] = []
        for index, bar in enumerate(bars):
            forward = bars[index + 1 : index + 1 + max_holding_period]
            if not forward:
                continue
            outcomes.append(
                self._simulate_single(
                    entry=bar.close_price,
                    forward=forward,
                    risk_ratio=risk_ratio,
                    target_1_ratio=target_1_ratio,
                    target_2_ratio=target_2_ratio,
                    target_3_ratio=target_3_ratio,
                )
            )
        return tuple(outcomes)

    def _simulate_single(
        self,
        *,
        entry: Decimal,
        forward: tuple[OHLCVBar, ...],
        risk_ratio: Decimal,
        target_1_ratio: Decimal,
        target_2_ratio: Decimal | None,
        target_3_ratio: Decimal | None,
    ) -> SetupOutcome:
        stop = entry * (Decimal("1") + risk_ratio)
        target_1 = entry * (Decimal("1") + target_1_ratio)
        target_2 = (
            entry * (Decimal("1") + target_2_ratio)
            if target_2_ratio is not None
            else None
        )
        target_3 = (
            entry * (Decimal("1") + target_3_ratio)
            if target_3_ratio is not None
            else None
        )
        target_1_hit = False
        target_2_hit = False
        target_3_hit = False
        stop_loss_hit = False
        lowest = entry
        exit_price = forward[-1].close_price
        holding_period = len(forward)
        for offset, bar in enumerate(forward, start=1):
            lowest = min(lowest, bar.low_price)
            if bar.low_price <= stop:
                stop_loss_hit = True
                exit_price = stop
                holding_period = offset
                break
            if bar.high_price >= target_1:
                target_1_hit = True
                exit_price = target_1
                holding_period = offset
            if target_2 is not None and bar.high_price >= target_2:
                target_2_hit = True
                exit_price = target_2
                holding_period = offset
            if target_3 is not None and bar.high_price >= target_3:
                target_3_hit = True
                exit_price = target_3
                holding_period = offset
                break
        return SetupOutcome(
            target_1_hit=target_1_hit,
            target_2_hit=target_2_hit,
            target_3_hit=target_3_hit,
            stop_loss_hit=stop_loss_hit,
            max_drawdown=(lowest - entry) / entry,
            holding_period_days=holding_period,
            return_ratio=(exit_price - entry) / entry,
        )


def _edge_confidence(sample_size: int) -> EdgeConfidence:
    if sample_size < 30:
        return EdgeConfidence.INSUFFICIENT_DATA
    if sample_size < 100:
        return EdgeConfidence.LOW
    if sample_size < 300:
        return EdgeConfidence.MEDIUM
    return EdgeConfidence.HIGH


def _relative_level(value: Decimal | None, reference: Decimal) -> Decimal | None:
    if value is None or reference <= _ZERO:
        return None
    return (value - reference) / reference


def _simple_average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, _ZERO) / Decimal(len(values))


def _hit_rate(values: Iterable[bool]) -> Decimal:
    bools = tuple(values)
    if not bools:
        return _ZERO
    hits = sum(1 for value in bools if value)
    return Decimal(hits) / Decimal(len(bools))


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, _ZERO) / Decimal(len(values))


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _median_int(values: tuple[int, ...]) -> int:
    if not values:
        return 0
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return int((ordered[midpoint - 1] + ordered[midpoint]) / 2)


def _fill_probability(
    strategy_type: TradeStrategyType,
    action: TradeStrategyAction,
) -> Decimal | None:
    if action is TradeStrategyAction.BUY_NOW:
        return Decimal("1.00")
    if strategy_type is TradeStrategyType.PULLBACK_ENTRY:
        return Decimal("0.52")
    if strategy_type is TradeStrategyType.AGGRESSIVE_ACCUMULATION:
        return Decimal("0.28")
    if action is TradeStrategyAction.WAIT_FOR_CONFIRMATION:
        return Decimal("0.44")
    return None


def _fill_window_days(
    strategy_type: TradeStrategyType,
    action: TradeStrategyAction,
) -> int | None:
    if action is TradeStrategyAction.BUY_NOW:
        return 0
    if strategy_type is TradeStrategyType.AGGRESSIVE_ACCUMULATION:
        return 20
    if strategy_type is TradeStrategyType.PULLBACK_ENTRY:
        return 10
    if action is TradeStrategyAction.WAIT_FOR_CONFIRMATION:
        return 5
    return None


def _trade_strategy_playbooks(
    *,
    trade_plan: RecommendationTradePlan,
    score: RecommendationScore,
    trade_setup: TradeSetupAssessment,
    price_history: tuple[OHLCVBar, ...],
) -> tuple[TradeStrategyPlaybook, ...]:
    if score.decision in {
        RecommendationDecision.AVOID,
        RecommendationDecision.SELL,
    }:
        return (
            _no_trade_strategy(
                trade_plan,
                "Avoid / exit. Setup is not actionable.",
                price_history,
            ),
        )

    if (
        score.decision
        in {
            RecommendationDecision.BUY,
            RecommendationDecision.STRONG_BUY,
        }
        and trade_setup.entry_ready
        and trade_plan.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    ):
        strategies = [
            _momentum_breakout_strategy(
                trade_plan,
                TradeStrategyAction.BUY_NOW,
                price_history,
            ),
            _pullback_strategy(trade_plan, price_history),
            _aggressive_accumulation_strategy(trade_plan, price_history),
        ]
        return tuple(strategy for strategy in strategies if strategy is not None)

    if score.decision is RecommendationDecision.WATCHLIST:
        strategies = [
            _confirmation_strategy(trade_plan, price_history),
            _pullback_strategy(trade_plan, price_history),
            _no_trade_strategy(
                trade_plan,
                "Wait. No capital is approved until the trigger confirms.",
                price_history,
            ),
        ]
        return tuple(strategy for strategy in strategies if strategy is not None)

    return (
        _no_trade_strategy(
            trade_plan,
            "No fresh deployment strategy is attractive yet.",
            price_history,
        ),
    )


def _momentum_breakout_strategy(
    trade_plan: RecommendationTradePlan,
    action: TradeStrategyAction,
    price_history: tuple[OHLCVBar, ...],
) -> TradeStrategyPlaybook:
    strategy_type = TradeStrategyType.MOMENTUM_BREAKOUT
    return TradeStrategyPlaybook(
        strategy_type=strategy_type,
        name="Momentum Breakout",
        action=action,
        strategy_rank=StrategyRank(
            rank=2 if action is TradeStrategyAction.BUY_NOW else 1,
            label="#2 Alternative"
            if action is TradeStrategyAction.BUY_NOW
            else "#1 Recommended",
            quality=StrategyQuality.GOOD,
            rationale=(
                "Immediate participation is valid, but entry efficiency is "
                "weaker than the pullback plan."
                if action is TradeStrategyAction.BUY_NOW
                else "Confirmation is required before capital is deployed."
            ),
        ),
        edge_stats=StatisticalEdgeEngine().assess(
            trade_plan=trade_plan,
            strategy_type=strategy_type,
            action=action,
            price_history=price_history,
        ),
        entry_zone_basis=_breakout_entry_basis(trade_plan),
        expected_wait_days=_fill_window_days(strategy_type, action),
        entry_low=trade_plan.entry_zone_low,
        entry_high=trade_plan.entry_zone_high,
        trigger_text=(
            "Already confirmed."
            if action is TradeStrategyAction.BUY_NOW
            else "Buy only after the confirmation trigger closes above the level."
        ),
        stop_loss=trade_plan.initial_stop_loss,
        stop_rule=_stop_rule(trade_plan.initial_stop_loss),
        trend_invalidation_reference=_trend_invalidation_reference(trade_plan),
        target_1=trade_plan.target_1,
        target_2=trade_plan.target_2,
        target_3=trade_plan.target_3,
        risk_reward=trade_plan.risk_reward_ratio,
        position_size_multiplier=Decimal("1.00"),
        expected_holding_period=trade_plan.expected_holding_period,
        explanation=(
            "Best if the user wants immediate participation. Breakout entry "
            "is actionable, but pullback entry offers better risk/reward if "
            "price retraces."
            if action is TradeStrategyAction.BUY_NOW
            else "Use only after price confirms the breakout trigger."
        ),
    )


def _confirmation_strategy(
    trade_plan: RecommendationTradePlan,
    price_history: tuple[OHLCVBar, ...],
) -> TradeStrategyPlaybook:
    strategy_type = TradeStrategyType.MOMENTUM_BREAKOUT
    action = TradeStrategyAction.WAIT_FOR_CONFIRMATION
    return TradeStrategyPlaybook(
        strategy_type=strategy_type,
        name="Confirmation Breakout",
        action=action,
        strategy_rank=StrategyRank(
            rank=1,
            label="#1 Recommended",
            quality=StrategyQuality.FAIR,
            rationale="Wait for confirmation before considering deployment.",
        ),
        edge_stats=StatisticalEdgeEngine().assess(
            trade_plan=trade_plan,
            strategy_type=strategy_type,
            action=action,
            price_history=price_history,
        ),
        entry_zone_basis=_breakout_entry_basis(trade_plan),
        expected_wait_days=_fill_window_days(strategy_type, action),
        entry_low=trade_plan.entry_zone_low,
        entry_high=trade_plan.entry_zone_high,
        trigger_text=_waiting_trigger_text(trade_plan),
        stop_loss=trade_plan.initial_stop_loss,
        stop_rule=_stop_rule(trade_plan.initial_stop_loss),
        trend_invalidation_reference=_trend_invalidation_reference(trade_plan),
        target_1=trade_plan.target_1,
        target_2=trade_plan.target_2,
        target_3=trade_plan.target_3,
        risk_reward=trade_plan.risk_reward_ratio,
        position_size_multiplier=Decimal("0.00"),
        expected_holding_period=trade_plan.expected_holding_period,
        explanation=(
            "Bullish setup is visible, but no capital is approved until the "
            "confirmation trigger fires."
        ),
    )


def _pullback_strategy(
    trade_plan: RecommendationTradePlan,
    price_history: tuple[OHLCVBar, ...],
) -> TradeStrategyPlaybook | None:
    if trade_plan.entry_price is None or trade_plan.initial_stop_loss is None:
        return None
    anchor = _pullback_anchor(trade_plan)
    if anchor is None or anchor <= trade_plan.initial_stop_loss:
        return None
    atr = trade_plan.atr_value or (trade_plan.entry_price * Decimal("0.02"))
    entry_low = _money(
        max(
            anchor - atr * Decimal("0.25"),
            trade_plan.initial_stop_loss + atr * Decimal("0.50"),
        )
    )
    entry_high = _money(min(anchor + atr, trade_plan.entry_price))
    if entry_high <= entry_low:
        return None
    risk_reward = _strategy_risk_reward(
        entry_price=entry_high,
        stop_loss=trade_plan.initial_stop_loss,
        target=trade_plan.target_1,
    )
    return TradeStrategyPlaybook(
        strategy_type=TradeStrategyType.PULLBACK_ENTRY,
        name="Pullback Entry",
        action=TradeStrategyAction.WAIT_FOR_PULLBACK,
        strategy_rank=StrategyRank(
            rank=1,
            label="#1 Recommended",
            quality=StrategyQuality.EXCELLENT
            if risk_reward is not None and risk_reward >= Decimal("2.50")
            else StrategyQuality.GOOD,
            rationale="Better risk/reward near technical support.",
        ),
        edge_stats=StatisticalEdgeEngine().assess(
            trade_plan=trade_plan,
            strategy_type=TradeStrategyType.PULLBACK_ENTRY,
            action=TradeStrategyAction.WAIT_FOR_PULLBACK,
            price_history=price_history,
        ),
        entry_zone_basis=_pullback_entry_basis(trade_plan, anchor),
        expected_wait_days=_fill_window_days(
            TradeStrategyType.PULLBACK_ENTRY,
            TradeStrategyAction.WAIT_FOR_PULLBACK,
        ),
        entry_low=entry_low,
        entry_high=entry_high,
        trigger_text=(
            "Buy only if price pulls back into this zone and holds with "
            "constructive candle/volume."
        ),
        stop_loss=trade_plan.initial_stop_loss,
        stop_rule=_stop_rule(trade_plan.initial_stop_loss),
        trend_invalidation_reference=_trend_invalidation_reference(trade_plan),
        target_1=trade_plan.target_1,
        target_2=trade_plan.target_2,
        target_3=trade_plan.target_3,
        risk_reward=risk_reward,
        position_size_multiplier=Decimal("0.75"),
        expected_holding_period=trade_plan.expected_holding_period,
        explanation=(
            "Better risk/reward than breakout entry, but lower fill "
            "probability because price may not retrace."
        ),
    )


def _aggressive_accumulation_strategy(
    trade_plan: RecommendationTradePlan,
    price_history: tuple[OHLCVBar, ...],
) -> TradeStrategyPlaybook | None:
    if trade_plan.entry_price is None:
        return None
    atr = trade_plan.atr_value or (trade_plan.entry_price * Decimal("0.02"))
    anchor = _deep_pullback_anchor(trade_plan)
    if anchor is None:
        return None
    entry_low = _money(max(anchor - atr * Decimal("0.50"), Decimal("0.01")))
    entry_high = _money(anchor + atr * Decimal("0.25"))
    stop_loss = _money(max(entry_low - atr, Decimal("0.01")))
    if stop_loss >= entry_low or entry_high >= trade_plan.entry_price:
        return None
    risk_reward = _strategy_risk_reward(
        entry_price=entry_high,
        stop_loss=stop_loss,
        target=trade_plan.target_1,
    )
    return TradeStrategyPlaybook(
        strategy_type=TradeStrategyType.AGGRESSIVE_ACCUMULATION,
        name="Aggressive Accumulation",
        action=TradeStrategyAction.WAIT_FOR_DEEP_PULLBACK,
        strategy_rank=StrategyRank(
            rank=3,
            label="#3 Aggressive",
            quality=StrategyQuality.SPECULATIVE,
            rationale="Highest reward/risk, but lowest fill probability.",
        ),
        edge_stats=StatisticalEdgeEngine().assess(
            trade_plan=trade_plan,
            strategy_type=TradeStrategyType.AGGRESSIVE_ACCUMULATION,
            action=TradeStrategyAction.WAIT_FOR_DEEP_PULLBACK,
            price_history=price_history,
        ),
        entry_zone_basis=_aggressive_entry_basis(trade_plan, anchor),
        expected_wait_days=_fill_window_days(
            TradeStrategyType.AGGRESSIVE_ACCUMULATION,
            TradeStrategyAction.WAIT_FOR_DEEP_PULLBACK,
        ),
        entry_low=entry_low,
        entry_high=entry_high,
        trigger_text=(
            "Buy only if price pulls back near support and shows reversal evidence."
        ),
        stop_loss=stop_loss,
        stop_rule=_stop_rule(stop_loss),
        trend_invalidation_reference=_trend_invalidation_reference(trade_plan),
        target_1=trade_plan.target_1,
        target_2=trade_plan.target_2,
        target_3=trade_plan.target_3,
        risk_reward=risk_reward,
        position_size_multiplier=Decimal("0.40"),
        expected_holding_period=trade_plan.expected_holding_period,
        explanation="Best risk/reward, lowest fill probability.",
    )


def _no_trade_strategy(
    trade_plan: RecommendationTradePlan,
    explanation: str,
    price_history: tuple[OHLCVBar, ...] = (),
) -> TradeStrategyPlaybook:
    return TradeStrategyPlaybook(
        strategy_type=TradeStrategyType.NO_TRADE,
        name="No Trade",
        action=TradeStrategyAction.AVOID,
        strategy_rank=StrategyRank(
            rank=None,
            label="Not Recommended",
            quality=StrategyQuality.NOT_SUITABLE,
            rationale="No attractive deployable strategy is available.",
        ),
        edge_stats=StatisticalEdgeEngine().assess(
            trade_plan=trade_plan,
            strategy_type=TradeStrategyType.NO_TRADE,
            action=TradeStrategyAction.AVOID,
            price_history=price_history,
        ),
        entry_zone_basis=(
            EntryZoneBasis(
                basis_type=EntryZoneBasisType.UNKNOWN,
                level=None,
                description="No actionable entry zone.",
            ),
        ),
        expected_wait_days=None,
        entry_low=None,
        entry_high=None,
        trigger_text="No actionable bullish trigger.",
        stop_loss=None,
        stop_rule="No new trade; keep capital unallocated.",
        trend_invalidation_reference=_trend_invalidation_reference(trade_plan),
        target_1=None,
        target_2=None,
        target_3=None,
        risk_reward=None,
        position_size_multiplier=Decimal("0.00"),
        expected_holding_period=trade_plan.expected_holding_period,
        explanation=explanation,
    )


def _stop_rule(stop_loss: Decimal | None) -> str:
    if stop_loss is None:
        return "No active trade; no risk stop is assigned."
    return f"{_money_text(stop_loss)} closing basis"


def _trend_invalidation_reference(trade_plan: RecommendationTradePlan) -> str | None:
    if trade_plan.dma_20_invalidation is None:
        return None
    return f"20-DMA {_money_text(trade_plan.dma_20_invalidation)}, not an active stop."


def _breakout_entry_basis(
    trade_plan: RecommendationTradePlan,
) -> tuple[EntryZoneBasis, ...]:
    basis: list[EntryZoneBasis] = []
    if trade_plan.entry_zone_low is not None:
        basis.append(
            EntryZoneBasis(
                basis_type=EntryZoneBasisType.BREAKOUT_LEVEL,
                level=trade_plan.entry_zone_low,
                description="Breakout level / confirmation zone.",
            )
        )
    if trade_plan.entry_price is not None:
        basis.append(
            EntryZoneBasis(
                basis_type=EntryZoneBasisType.RECENT_CLOSE,
                level=trade_plan.entry_price,
                description="Recent close or confirmation trigger.",
            )
        )
    return tuple(basis) or (
        EntryZoneBasis(
            basis_type=EntryZoneBasisType.UNKNOWN,
            level=None,
            description="Breakout entry basis unavailable.",
        ),
    )


def _pullback_entry_basis(
    trade_plan: RecommendationTradePlan,
    anchor: Decimal,
) -> tuple[EntryZoneBasis, ...]:
    basis_type = EntryZoneBasisType.SUPPORT
    description = "Pullback support zone."
    if trade_plan.nearest_fibonacci_level == anchor:
        basis_type = EntryZoneBasisType.FIBONACCI_RETRACEMENT
        description = "Fibonacci retracement support."
    elif trade_plan.dma_20_invalidation == anchor:
        basis_type = EntryZoneBasisType.MOVING_AVERAGE_20
        description = "20-DMA pullback reference."
    elif trade_plan.entry_zone_low == anchor:
        basis_type = EntryZoneBasisType.PRIOR_RESISTANCE
        description = "Prior breakout level / resistance retest."
    return (
        EntryZoneBasis(
            basis_type=basis_type,
            level=anchor,
            description=description,
        ),
        EntryZoneBasis(
            basis_type=EntryZoneBasisType.ATR_BAND,
            level=trade_plan.atr_value,
            description="ATR-adjusted retracement band.",
        ),
    )


def _aggressive_entry_basis(
    trade_plan: RecommendationTradePlan,
    anchor: Decimal,
) -> tuple[EntryZoneBasis, ...]:
    basis_type = EntryZoneBasisType.SUPPORT
    description = "Deep retracement support area."
    if trade_plan.swing_low == anchor:
        basis_type = EntryZoneBasisType.SWING_LOW
        description = "Prior swing low / deep support."
    elif trade_plan.dma_50 == anchor:
        basis_type = EntryZoneBasisType.MOVING_AVERAGE_50
        description = "50-DMA deep pullback reference."
    return (
        EntryZoneBasis(
            basis_type=basis_type,
            level=anchor,
            description=description,
        ),
        EntryZoneBasis(
            basis_type=EntryZoneBasisType.ATR_BAND,
            level=trade_plan.atr_value,
            description="ATR-adjusted support area.",
        ),
    )


def _waiting_trigger_text(trade_plan: RecommendationTradePlan) -> str:
    if trade_plan.entry_price is None:
        return "Wait for a valid confirmation trigger."
    if trade_plan.trigger_status is TriggerStatus.WAITING_FOR_VOLUME_CONFIRMATION:
        return (
            f"Buy only after breakout above {_money_text(trade_plan.entry_price)} "
            "with above-average volume."
        )
    if trade_plan.trigger_status is TriggerStatus.WAITING_FOR_CROSS_ABOVE:
        return (
            f"Buy only after price crosses above {_money_text(trade_plan.entry_price)}."
        )
    return f"Buy only after daily close above {_money_text(trade_plan.entry_price)}."


def _pullback_anchor(trade_plan: RecommendationTradePlan) -> Decimal | None:
    if trade_plan.entry_price is None:
        return None
    candidates = tuple(
        value
        for value in (
            trade_plan.support_level_used,
            trade_plan.dma_20_invalidation,
            trade_plan.nearest_fibonacci_level,
            trade_plan.entry_zone_low,
        )
        if value is not None and value < trade_plan.entry_price
    )
    return max(candidates, default=None)


def _deep_pullback_anchor(trade_plan: RecommendationTradePlan) -> Decimal | None:
    if trade_plan.entry_price is None:
        return None
    candidates = tuple(
        value
        for value in (
            trade_plan.support_level_used,
            trade_plan.swing_low,
            trade_plan.dma_50,
            trade_plan.nearest_fibonacci_level,
            trade_plan.initial_stop_loss,
        )
        if value is not None and value < trade_plan.entry_price
    )
    return min(candidates, default=None)


def _strategy_risk_reward(
    *,
    entry_price: Decimal,
    stop_loss: Decimal,
    target: Decimal | None,
) -> Decimal | None:
    if target is None or stop_loss >= entry_price:
        return None
    risk = entry_price - stop_loss
    reward = target - entry_price
    if risk <= _ZERO or reward <= _ZERO:
        return None
    return _quantize(reward / risk)


def _has_valid_trade_plan(trade_plan: RecommendationTradePlan) -> bool:
    return (
        trade_plan.entry_price is not None
        and trade_plan.entry_zone_low is not None
        and trade_plan.entry_zone_high is not None
        and trade_plan.initial_stop_loss is not None
        and trade_plan.target_1 is not None
        and trade_plan.initial_stop_loss < trade_plan.entry_price
    )


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


def _is_late_setup(candidate: RecommendationCandidate) -> bool:
    if (
        candidate.current_price is None
        or candidate.resistance_level is None
        or candidate.atr is None
    ):
        return False
    late_threshold = candidate.resistance_level + candidate.atr * Decimal("2")
    return candidate.current_price > late_threshold


def _within_percent(
    value: Decimal | None,
    level: Decimal | None,
    percent: str,
) -> bool:
    if value is None or level is None or level <= _ZERO:
        return False
    tolerance = level * (Decimal(percent) / _HUNDRED)
    return abs(value - level) <= tolerance


def _near_any_level(
    value: Decimal | None,
    levels: tuple[Decimal | None, ...],
    atr: Decimal | None,
) -> bool:
    if value is None:
        return False
    tolerance = atr if atr is not None else max(value * Decimal("0.02"), Decimal("1"))
    return any(
        level is not None and abs(value - level) <= tolerance for level in levels
    )


def _volume_ratio(candidate: RecommendationCandidate) -> Decimal:
    volume = _metadata_decimal(candidate, "volume")
    average_volume = _metadata_decimal(candidate, "average_volume")
    if volume is None or average_volume is None or average_volume <= _ZERO:
        return _ONE
    return volume / average_volume


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


def _apply_historical_edge_adjustment(
    score: RecommendationScore,
    metadata: Mapping[str, str],
) -> RecommendationScore:
    raw_ev = metadata.get("historical_setup_ev_pct")
    if raw_ev is None or raw_ev == "unavailable":
        return score
    try:
        ev = Decimal(raw_ev)
    except Exception:
        return score
    adjustment = max(Decimal("-5"), min(Decimal("5"), ev))
    adjusted_score = max(
        Decimal("0"),
        min(Decimal("100"), score.score + adjustment),
    ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return replace(score, score=adjusted_score)


def _has_minimum_trade_plan_context(candidate: RecommendationCandidate) -> bool:
    return (
        candidate.current_price is not None
        and candidate.atr is not None
        and candidate.dma_20 is not None
        and candidate.swing_high is not None
        and candidate.swing_low is not None
        and (
            candidate.resistance_level is not None
            or candidate.support_level is not None
            or candidate.dma_50 is not None
        )
    )


def _has_retracement_context(candidate: RecommendationCandidate) -> bool:
    return (
        candidate.swing_high is not None
        and candidate.swing_low is not None
        and candidate.swing_high > candidate.swing_low
    )


def _hard_risk_candle_reason(
    candidate: RecommendationCandidate,
    price_volume: PriceVolumeAssessment,
    candle_pattern: CandlePatternAssessment,
) -> str | None:
    bearish_patterns = {
        "BEARISH_ENGULFING",
        "SHOOTING_STAR",
        "EVENING_STAR",
        "STRONG_BEARISH_CLOSE",
    }
    if candle_pattern.pattern not in bearish_patterns:
        return None

    high_volume = price_volume.volume_evidence.volume_vs_average >= Decimal("2.00")
    below_support = candidate.support_level is not None and _is_below(
        candidate.current_price, candidate.support_level
    )
    failed_breakout = (
        candidate.breakout_attempt
        and candidate.resistance_level is not None
        and _is_below(candidate.current_price, candidate.resistance_level)
    )
    extended_move = (
        candidate.current_price is not None
        and candidate.dma_20 is not None
        and candidate.atr is not None
        and candidate.atr > _ZERO
        and candidate.current_price - candidate.dma_20 >= candidate.atr * Decimal("3")
    )

    if below_support and candle_pattern.pattern == "BEARISH_ENGULFING":
        return "bearish engulfing closed below key support"
    if failed_breakout and high_volume:
        return "failed breakout candle closed below breakout level on high volume"
    if high_volume and extended_move:
        return "bearish reversal candle on very high volume after extended move"
    return None


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _money_optional(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _money(value)


def _optional_quantize(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _quantize(value)


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"₹{_money(value)}"


def _candidate_with_latest_ohlcv(
    candidate: RecommendationCandidate,
) -> RecommendationCandidate:
    if not candidate.price_history:
        return candidate

    latest = candidate.price_history[-1]
    previous = (
        candidate.price_history[-2] if len(candidate.price_history) >= 2 else None
    )
    two_day_prior = (
        candidate.price_history[-3] if len(candidate.price_history) >= 3 else None
    )
    market_levels = TradePlanIntelligenceEngine().market_levels(candidate)
    metadata = dict(candidate.metadata)
    metadata["historical_bars"] = str(market_levels.historical_bar_count)
    metadata["volume"] = str(latest.volume)
    current_price = candidate.current_price or latest.close_price
    metadata["current_price"] = str(_money(current_price))
    metadata["price"] = str(_money(current_price))
    if len(candidate.price_history) >= 20:
        lookback = (
            candidate.price_history[-21:-1]
            if len(candidate.price_history) >= 21
            else candidate.price_history[-20:]
        )
        average_volume = sum((bar.volume for bar in lookback), _ZERO) / Decimal(
            len(lookback)
        )
        metadata["average_volume"] = str(_quantize(average_volume))
    return replace(
        candidate,
        metadata=metadata,
        open_price=candidate.open_price or latest.open_price,
        high_price=candidate.high_price or latest.high_price,
        low_price=candidate.low_price or latest.low_price,
        current_price=current_price,
        dma_20=candidate.dma_20 or market_levels.dma_20,
        dma_50=candidate.dma_50 or market_levels.dma_50,
        dma_200=candidate.dma_200 or market_levels.dma_200,
        atr=candidate.atr or market_levels.atr_14,
        swing_high=candidate.swing_high or market_levels.recent_swing_high,
        swing_low=candidate.swing_low or market_levels.recent_swing_low,
        fibonacci_382=candidate.fibonacci_382 or market_levels.fibonacci.level_382,
        fibonacci_500=candidate.fibonacci_500 or market_levels.fibonacci.level_500,
        fibonacci_618=candidate.fibonacci_618 or market_levels.fibonacci.level_618,
        fibonacci_786=candidate.fibonacci_786 or market_levels.fibonacci.level_786,
        previous_open_price=(
            candidate.previous_open_price
            or (previous.open_price if previous is not None else None)
        ),
        previous_high_price=(
            candidate.previous_high_price
            or (previous.high_price if previous is not None else None)
        ),
        previous_low_price=(
            candidate.previous_low_price
            or (previous.low_price if previous is not None else None)
        ),
        previous_close=(
            candidate.previous_close
            or (previous.close_price if previous is not None else None)
        ),
        two_day_prior_open_price=(
            candidate.two_day_prior_open_price
            or (two_day_prior.open_price if two_day_prior is not None else None)
        ),
        two_day_prior_high_price=(
            candidate.two_day_prior_high_price
            or (two_day_prior.high_price if two_day_prior is not None else None)
        ),
        two_day_prior_low_price=(
            candidate.two_day_prior_low_price
            or (two_day_prior.low_price if two_day_prior is not None else None)
        ),
        two_day_prior_close=(
            candidate.two_day_prior_close
            or (two_day_prior.close_price if two_day_prior is not None else None)
        ),
    )


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
        return "20-DMA invalidation unavailable due to insufficient price history."
    return f"Trade invalid if daily close is below 20-DMA, currently ₹{level}."


def _quantize(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def _as_percent(value: Decimal) -> str:
    percentage = (Decimal(str(value)) * _HUNDRED).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return f"{percentage}%"
