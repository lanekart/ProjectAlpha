from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.recommendation_intelligence import (
    OHLCVBar,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationEngine,
    RecommendationEvidence,
    RecommendationRisk,
    TradePlanIntelligenceEngine,
)


def test_recommendation_engine_aligns_buy_action_with_buy_score() -> None:
    report = RecommendationEngine().build((_history_candidate(symbol="HAL"),))[0]

    assert Decimal("60") <= report.score < Decimal("75")
    assert report.action is RecommendationAction.ACCUMULATE
    assert report.decision is RecommendationDecision.WATCHLIST
    assert report.setup_stage == "READY_FOR_CONFIRMATION"
    assert "Action: ACCUMULATE" in report.explanation


def test_recommendation_engine_does_not_emit_buy_for_low_score() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                symbol="WEAK",
                strategy_score=Decimal("0.18"),
                probability_score=Decimal("0.22"),
                market_intelligence_score=Decimal("0.20"),
                liquidity_score=Decimal("0.35"),
                risk_score=Decimal("0.25"),
            ),
        )
    )[0]

    assert report.score < Decimal("50")
    assert report.action is RecommendationAction.AVOID
    assert report.decision is RecommendationDecision.SELL
    assert "Action: AVOID" in report.explanation


def test_recommendation_engine_keeps_watchlist_non_buy() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                symbol="MID",
                strategy_score=Decimal("0.62"),
                probability_score=Decimal("0.56"),
                market_intelligence_score=Decimal("0.55"),
                liquidity_score=Decimal("0.60"),
                risk_score=Decimal("0.58"),
            ),
        )
    )[0]

    assert Decimal("60") <= report.score < Decimal("75")
    assert report.action is RecommendationAction.ACCUMULATE
    assert report.decision is RecommendationDecision.WATCHLIST
    assert "Action: ACCUMULATE" in report.explanation


def test_healthy_retracement_improves_buy_score() -> None:
    healthy = _retracement_candidate(retracement_score=Decimal("0.92"))
    neutral = _retracement_candidate(
        symbol="NEUTRAL",
        retracement_score=Decimal("0.50"),
    )

    healthy_report, neutral_report = RecommendationEngine().build((healthy, neutral))

    assert healthy_report.symbol == "HEALTHY"
    assert healthy_report.final_signal in {"BUY", "STRONG_BUY"}
    assert healthy_report.score > neutral_report.score
    assert healthy_report.retracement_weight == Decimal("0.1000")
    assert healthy_report.score_breakdown.retracement_points == Decimal("9.2000")


def test_deep_retracement_reduces_score() -> None:
    deep = _retracement_candidate(symbol="DEEP", retracement_score=Decimal("0.18"))
    healthy = _retracement_candidate(
        symbol="HEALTHY",
        retracement_score=Decimal("0.92"),
    )

    reports = RecommendationEngine().build((deep, healthy))
    deep_report = next(report for report in reports if report.symbol == "DEEP")
    healthy_report = next(report for report in reports if report.symbol == "HEALTHY")

    assert deep_report.score < healthy_report.score
    assert deep_report.score_breakdown.retracement_points < Decimal("3")


def test_breakdown_below_618_reduces_signal_to_avoid() -> None:
    report = RecommendationEngine().build(
        (
            _retracement_candidate(
                symbol="BREACH618",
                current_price=Decimal("92"),
                fibonacci_618=Decimal("95"),
                fibonacci_786=Decimal("88"),
            ),
        )
    )[0]

    assert report.final_signal == "AVOID"
    assert report.final_score <= Decimal("59")
    assert report.invalidation_level == Decimal("95.00")
    assert "61.8% Fibonacci" in report.invalidation_reason


def test_breakdown_below_786_can_generate_sell_reject() -> None:
    report = RecommendationEngine().build(
        (
            _retracement_candidate(
                symbol="BREACH786",
                current_price=Decimal("84"),
                fibonacci_618=Decimal("95"),
                fibonacci_786=Decimal("88"),
            ),
        )
    )[0]

    assert report.final_signal == "SELL"
    assert report.final_score <= Decimal("35")
    assert "78.6% Fibonacci" in report.invalidation_reason


def test_entry_zone_is_produced_for_constructive_retracement() -> None:
    report = RecommendationEngine().build((_retracement_candidate(),))[0]

    assert report.entry_zone_low == Decimal("101.00")
    assert report.entry_zone_high > report.entry_zone_low
    assert report.retracement_zone == "20-DMA"
    assert report.nearest_fibonacci_level == Decimal("100.00")


def test_stop_loss_is_below_support_and_retracement_low() -> None:
    report = RecommendationEngine().build((_retracement_candidate(),))[0]

    assert report.initial_stop_loss < report.support_level_used
    assert report.initial_stop_loss < Decimal("101")


def test_targets_are_generated_from_risk_reward_logic() -> None:
    report = RecommendationEngine().build((_retracement_candidate(),))[0]
    risk = report.entry_price - report.initial_stop_loss

    assert report.target_1 == report.entry_price + (risk * Decimal("2"))
    assert report.target_2 == report.entry_price + (risk * Decimal("3"))
    assert report.risk_reward_ratio == Decimal("2.0000")


def test_20_dma_invalidation_includes_actual_numeric_value() -> None:
    report = RecommendationEngine().build(
        (
            _retracement_candidate(
                symbol="DMA20",
                fibonacci_618=None,
                fibonacci_786=None,
            ),
        )
    )[0]

    assert report.invalidation_level == Decimal("101.00")
    assert any("Invalidation level: 101.00" in line for line in report.explanation)


def test_final_explanation_includes_retracement_contribution() -> None:
    report = RecommendationEngine().build((_retracement_candidate(),))[0]

    assert any("Retracement contribution" in line for line in report.explanation)
    assert "Retracement improved the signal" in report.trade_plan_explanation


def test_evidence_assessment_scores_bullish_and_bearish_signals() -> None:
    report = RecommendationEngine().build(
        (
            _evidence_candidate(
                current_price=Decimal("104"),
                dma_20=Decimal("101"),
                dma_50=Decimal("114"),
                ema_200=Decimal("108"),
                relative_strength_score=Decimal("0.82"),
                volume_confirmation_score=Decimal("0.35"),
                metadata={"volume": "10000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.evidence_score == report.evidence_assessment.score
    assert any(signal.label == "Price structure" for signal in report.bullish_evidence)
    assert any(
        signal.label == "Volume confirmation" for signal in report.bearish_evidence
    )
    assert report.evidence_assessment.conflict_penalty_points > Decimal("0")


def test_regime_aware_weights_reward_bull_and_penalize_bear_setups() -> None:
    bull = _evidence_candidate(symbol="BULL", market_regime="BULL")
    bear = _evidence_candidate(symbol="BEAR", market_regime="BEAR")

    reports = RecommendationEngine().build((bull, bear))
    bull_report = next(report for report in reports if report.symbol == "BULL")
    bear_report = next(report for report in reports if report.symbol == "BEAR")

    assert bull_report.score > bear_report.score
    assert bull_report.evidence_assessment.regime_adjustment_points > Decimal("0")
    assert bear_report.evidence_assessment.regime_adjustment_points < Decimal("0")
    assert "Bear market raises quality threshold" in (
        bear_report.evidence_assessment.regime_reason
    )


def test_sideways_market_reduces_breakout_confidence() -> None:
    report = RecommendationEngine().build(
        (
            _evidence_candidate(
                symbol="SIDEWAYS",
                market_regime="SIDEWAYS",
                setup_type="BREAKOUT",
            ),
        )
    )[0]

    assert report.evidence_assessment.regime_adjustment_points < Decimal("0")
    assert "Sideways market reduces breakout confidence" in (
        report.evidence_assessment.regime_reason
    )


def test_setup_quality_classifies_weak_random_signal() -> None:
    report = RecommendationEngine().build(
        (
            _evidence_candidate(
                symbol="WEAKSETUP",
                setup_type="WEAK_RANDOM",
                strategy_score=Decimal("0.30"),
                breakout_setup_score=Decimal("0.72"),
            ),
        )
    )[0]

    assert report.setup_quality.setup_type == "WEAK_RANDOM"
    assert report.setup_quality.classification == "WEAK"
    assert report.setup_quality.score <= Decimal("0.3000")


def test_trade_plan_includes_20_dma_invalidation_and_atr_trailing_stop() -> None:
    report = RecommendationEngine().build((_evidence_candidate(),))[0]

    assert report.trade_plan.dma_20_invalidation == Decimal("101.00")
    assert report.trade_plan.atr_value == Decimal("2.00")
    assert "Trade invalid if daily close is below 20-DMA, currently ₹101.00." in (
        report.trade_plan_explanation
    )
    assert "Trail at 2 x ATR (4)" in report.trailing_stop_strategy


def test_trade_plan_engine_calculates_market_levels() -> None:
    levels = TradePlanIntelligenceEngine().market_levels(
        _history_candidate(setup_type="BREAKOUT")
    )

    assert levels.atr_14 == Decimal("4.00")
    assert levels.dma_20 == Decimal("149.50")
    assert levels.dma_50 == Decimal("134.50")
    assert levels.recent_swing_high == Decimal("161.00")
    assert levels.recent_swing_low == Decimal("98.00")
    assert levels.fibonacci.level_382 == Decimal("136.93")
    assert levels.fibonacci.level_500 == Decimal("129.50")
    assert levels.fibonacci.level_618 == Decimal("122.07")


def test_relative_volume_uses_rolling_20_day_average() -> None:
    report = RecommendationEngine().build(
        (_history_candidate(symbol="RELVOL", setup_type="BREAKOUT"),)
    )[0]

    assert report.volume_evidence.volume_vs_average == Decimal(
        "1.070707070707070707070707071"
    )
    assert report.relative_volume == Decimal("1.0707")


def test_trade_plan_engine_calculates_breakout_entry_stop_and_targets() -> None:
    report = RecommendationEngine().build((_history_candidate(setup_type="BREAKOUT"),))[
        0
    ]

    assert report.entry_price == Decimal("160.00")
    assert report.entry_zone_low == Decimal("160.00")
    assert report.entry_zone_high == Decimal("162.00")
    assert report.initial_stop_loss is not None
    assert report.initial_stop_loss < report.entry_price
    assert report.initial_stop_loss >= Decimal("0")
    assert report.target_1 is not None
    assert report.target_2 is not None
    assert report.target_3 is not None
    assert report.target_1 == report.entry_price + (
        (report.entry_price - report.initial_stop_loss) * Decimal("2")
    )
    assert report.target_2 == report.entry_price + (
        (report.entry_price - report.initial_stop_loss) * Decimal("3")
    )
    assert report.target_3 > report.entry_price


def test_trade_plan_engine_calculates_retracement_entry_zone() -> None:
    report = RecommendationEngine().build(
        (
            _history_candidate(
                setup_type="PULLBACK",
                breakout_attempt=False,
                resistance_level=Decimal("170"),
                prior_day_high=Decimal("157"),
            ),
        )
    )[0]

    assert report.entry_zone_low == Decimal("149.50")
    assert report.entry_zone_high == Decimal("151.50")
    assert report.entry_price == Decimal("161.00")


def test_trade_plan_engine_returns_unavailable_when_data_is_insufficient() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                symbol="NODATA",
                strategy_score=Decimal("0.90"),
                probability_score=Decimal("0.88"),
                market_intelligence_score=Decimal("0.86"),
                liquidity_score=Decimal("0.86"),
                risk_score=Decimal("0.86"),
            ),
        )
    )[0]

    assert report.entry_price is None
    assert report.initial_stop_loss is None
    assert report.target_1 is None
    assert report.trade_plan.atr_value is None
    assert report.trade_plan.dma_20_invalidation is None
    assert "insufficient price history" in report.trade_plan_explanation
    assert any("20-DMA unavailable" in reason for reason in report.unavailable_reasons)


def test_retracement_unavailable_remains_neutral() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                symbol="NORETRACE",
                strategy_score=Decimal("0.80"),
                probability_score=Decimal("0.78"),
                market_intelligence_score=Decimal("0.76"),
                liquidity_score=Decimal("0.74"),
                risk_score=Decimal("0.76"),
                retracement_score=Decimal("0.95"),
            ),
        )
    )[0]

    assert report.score_breakdown.retracement_points == Decimal("5.0000")
    assert "Retracement improved the signal" not in report.trade_plan_explanation


def test_candle_engine_receives_latest_ohlc_from_price_history() -> None:
    report = RecommendationEngine().build((_engulfing_history_candidate(),))[0]

    assert report.candle_pattern == "BULLISH_ENGULFING"
    assert report.candle_entry_trigger == Decimal("112.00")
    assert report.candle_stop_level == Decimal("98.00")


def test_confidence_and_top_evidence_contributors_are_explainable() -> None:
    report = RecommendationEngine().build((_evidence_candidate(),))[0]

    assert report.confidence_score == report.evidence_assessment.confidence_score
    assert Decimal("0") < report.confidence_score <= Decimal("1")
    assert len(report.evidence_assessment.top_contributors) == 3
    assert any("Top evidence contributors:" in line for line in report.explanation)


def test_historical_expectancy_hooks_default_to_unavailable() -> None:
    report = RecommendationEngine().build((_evidence_candidate(),))[0]

    assert report.historical_expectancy.status == "unavailable"
    assert report.historical_expectancy.win_rate is None
    assert any(
        "Historical expectancy: unavailable" in line for line in report.explanation
    )


def test_historical_expectancy_accepts_available_calibration_values() -> None:
    report = RecommendationEngine().build(
        (
            _evidence_candidate(
                historical_win_rate=Decimal("0.57"),
                historical_average_gain=Decimal("0.14"),
                historical_average_loss=Decimal("0.06"),
                historical_expected_value=Decimal("0.052"),
                historical_average_hold_days=Decimal("21"),
            ),
        )
    )[0]

    assert report.historical_expectancy.status == "available"
    assert report.historical_expectancy.win_rate == Decimal("0.5700")
    assert report.historical_expectancy.expected_value == Decimal("0.052")


def test_explainability_includes_evidence_breakdown_and_regime_trade_logic() -> None:
    report = RecommendationEngine().build((_evidence_candidate(),))[0]

    assert any("Evidence Score:" in line for line in report.explanation)
    assert any("Bullish evidence:" in line for line in report.explanation)
    assert any("Bearish evidence:" in line for line in report.explanation)
    assert any("Regime adjustment:" in line for line in report.explanation)
    assert any("20-DMA invalidation:" in line for line in report.explanation)
    assert any("Trailing stop:" in line for line in report.explanation)


def test_breakout_with_strong_volume_improves_buy_score() -> None:
    strong = _price_volume_candidate(symbol="STRONGVOL")
    weak = _price_volume_candidate(
        symbol="WEAKVOL",
        metadata={"volume": "50000", "average_volume": "100000"},
    )

    reports = RecommendationEngine().build((strong, weak))
    strong_report = next(report for report in reports if report.symbol == "STRONGVOL")
    weak_report = next(report for report in reports if report.symbol == "WEAKVOL")

    assert strong_report.score > weak_report.score
    assert strong_report.volume_evidence.breakout_volume_confirmation > Decimal("0.90")
    assert strong_report.action is RecommendationAction.BUY


def test_breakout_with_weak_volume_is_rejected_or_downgraded() -> None:
    report = RecommendationEngine().build(
        (
            _price_volume_candidate(
                symbol="WEAKBREAKOUT",
                metadata={"volume": "40000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.score < Decimal("60")
    assert report.action is RecommendationAction.AVOID
    assert any(
        "breakout occurred on weak volume" in line for line in report.explanation
    )


def test_pullback_on_low_volume_improves_retracement_score() -> None:
    report = RecommendationEngine().build(
        (
            _price_volume_candidate(
                symbol="LOWVOLPULLBACK",
                setup_type="PULLBACK",
                breakout_attempt=False,
                current_price=Decimal("101"),
                resistance_level=Decimal("108"),
                volume_dry_up_score=Decimal("0.85"),
                breakout_volume_confirmation=Decimal("0.75"),
            ),
        )
    )[0]

    assert report.price_evidence.retracement_state == "HEALTHY"
    assert report.score_breakdown.retracement_points >= Decimal("8")


def test_high_volume_selloff_damages_retracement_score() -> None:
    report = RecommendationEngine().build(
        (
            _price_volume_candidate(
                symbol="SELLVOL",
                setup_type="PULLBACK",
                breakout_attempt=False,
                current_price=Decimal("94"),
                previous_close=Decimal("101"),
                support_level=Decimal("96"),
                resistance_level=Decimal("108"),
                selloff_volume_penalty=Decimal("0.90"),
                metadata={"volume": "220000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.price_evidence.retracement_state == "BAD"
    assert report.score_breakdown.retracement_points < Decimal("5")


def test_lower_high_lower_low_structure_blocks_buy() -> None:
    report = RecommendationEngine().build(
        (
            _price_volume_candidate(
                symbol="LOWERLOW",
                lower_highs_lower_lows=True,
            ),
        )
    )[0]

    assert report.action is RecommendationAction.AVOID
    assert report.final_signal != "BUY"
    assert any("lower highs and lower lows" in line for line in report.explanation)


def test_breakdown_on_heavy_volume_generates_sell_or_avoid() -> None:
    report = RecommendationEngine().build(
        (
            _price_volume_candidate(
                symbol="HEAVYBREAK",
                breakout_attempt=False,
                breakdown_attempt=True,
                current_price=Decimal("93"),
                previous_close=Decimal("99"),
                support_level=Decimal("96"),
                resistance_level=Decimal("108"),
                metadata={"volume": "240000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.final_signal in {"SELL", "AVOID"}
    assert report.action is RecommendationAction.AVOID
    assert report.volume_evidence.selloff_volume_penalty >= Decimal("0.70")


def test_price_volume_evidence_appears_in_recommendation_explanation() -> None:
    report = RecommendationEngine().build((_price_volume_candidate(),))[0]

    assert any("Price action:" in line for line in report.explanation)
    assert any("Volume action:" in line for line in report.explanation)
    assert any("Price-volume verdict:" in line for line in report.explanation)
    assert any("Volume confirmation required:" in line for line in report.explanation)


def test_bullish_engulfing_near_support_improves_buy_score() -> None:
    bullish = _candle_candidate(symbol="BULLENGULF")
    neutral = _candle_candidate(
        symbol="NEUTRALCANDLE",
        open_price=Decimal("102"),
        current_price=Decimal("102.20"),
        high_price=Decimal("104"),
        low_price=Decimal("100"),
        previous_open_price=Decimal("102"),
        previous_close=Decimal("102.10"),
    )

    reports = RecommendationEngine().build((bullish, neutral))
    bullish_report = next(report for report in reports if report.symbol == "BULLENGULF")
    neutral_report = next(
        report for report in reports if report.symbol == "NEUTRALCANDLE"
    )

    assert bullish_report.candle_pattern == "BULLISH_ENGULFING"
    assert bullish_report.score > neutral_report.score
    assert bullish_report.candle_confirmation == "CONFIRMS"


def test_hammer_near_20_dma_improves_retracement_buy_setup() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="HAMMER",
                setup_type="PULLBACK",
                breakout_attempt=False,
                open_price=Decimal("103"),
                current_price=Decimal("104"),
                high_price=Decimal("105"),
                low_price=Decimal("100"),
                previous_open_price=Decimal("105"),
                previous_close=Decimal("102"),
                support_level=Decimal("101"),
                resistance_level=Decimal("108"),
            ),
        )
    )[0]

    assert report.candle_pattern == "HAMMER"
    assert report.candle_score >= Decimal("0.7000")
    assert report.score_breakdown.retracement_points >= Decimal("7")


def test_bearish_engulfing_near_resistance_reduces_score() -> None:
    bearish = _candle_candidate(
        symbol="BEARENGULF",
        open_price=Decimal("106"),
        current_price=Decimal("99"),
        high_price=Decimal("107"),
        low_price=Decimal("98"),
        previous_open_price=Decimal("100"),
        previous_close=Decimal("105"),
        resistance_level=Decimal("106"),
        breakout_attempt=True,
    )
    bullish = _candle_candidate(symbol="BULLENGULF")

    reports = RecommendationEngine().build((bearish, bullish))
    bearish_report = next(report for report in reports if report.symbol == "BEARENGULF")
    bullish_report = next(report for report in reports if report.symbol == "BULLENGULF")

    assert bearish_report.candle_pattern == "BEARISH_ENGULFING"
    assert bearish_report.candle_confirmation == "CONFLICTS"
    assert bearish_report.score < bullish_report.score


def test_shooting_star_on_high_volume_generates_warning() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="SHOOTING",
                open_price=Decimal("103"),
                current_price=Decimal("102"),
                high_price=Decimal("109"),
                low_price=Decimal("101"),
                previous_open_price=Decimal("100"),
                previous_close=Decimal("104"),
                resistance_level=Decimal("108"),
                metadata={"volume": "250000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.candle_pattern == "SHOOTING_STAR"
    assert report.candle_confirmation == "CONFLICTS"
    assert any("Candle pattern:" in line for line in report.explanation)


def test_candle_conflict_downgrades_without_forcing_avoid_when_not_hard_risk() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="SOFTCONFLICT",
                open_price=Decimal("103"),
                current_price=Decimal("102"),
                high_price=Decimal("109"),
                low_price=Decimal("101"),
                previous_open_price=Decimal("100"),
                previous_close=Decimal("104"),
                breakout_attempt=False,
                resistance_level=Decimal("115"),
                strategy_score=Decimal("0.95"),
                relative_strength_score=Decimal("0.94"),
                volume_confirmation_score=Decimal("0.92"),
                breakout_setup_score=Decimal("0.90"),
                metadata={"volume": "180000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.candle_pattern == "SHOOTING_STAR"
    assert report.candle_confirmation == "CONFLICTS"
    assert report.final_signal != "AVOID"
    assert not any("Hard-risk override:" in line for line in report.explanation)


def test_hard_risk_candle_override_requires_high_volume_context() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="HARDRISK",
                open_price=Decimal("106"),
                current_price=Decimal("99"),
                high_price=Decimal("107"),
                low_price=Decimal("98"),
                previous_open_price=Decimal("100"),
                previous_close=Decimal("105"),
                resistance_level=Decimal("106"),
                breakout_attempt=True,
                metadata={"volume": "250000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.candle_pattern == "BEARISH_ENGULFING"
    assert report.final_signal == "AVOID"
    assert any("Hard-risk override:" in line for line in report.explanation)


def test_doji_alone_does_not_create_buy() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="DOJI",
                open_price=Decimal("100"),
                current_price=Decimal("100.05"),
                high_price=Decimal("104"),
                low_price=Decimal("96"),
                previous_open_price=Decimal("101"),
                previous_close=Decimal("100"),
                strategy_score=Decimal("0.45"),
                relative_strength_score=Decimal("0.45"),
                breakout_setup_score=Decimal("0.45"),
                volume_confirmation_score=Decimal("0.45"),
                breakout_attempt=False,
                resistance_level=Decimal("108"),
                metadata={"volume": "100000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.candle_pattern == "DOJI"
    assert report.candle_score <= Decimal("0.5400")
    assert report.action is not RecommendationAction.BUY


def test_bullish_candle_without_volume_confirmation_gets_limited_score() -> None:
    report = RecommendationEngine().build(
        (
            _candle_candidate(
                symbol="LOWVOLCANDLE",
                metadata={"volume": "50000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.candle_pattern == "BULLISH_ENGULFING"
    assert report.candle_score <= Decimal("0.5800")
    assert report.candle_confirmation != "CONFIRMS"


def test_candle_entry_and_stop_levels_are_generated_correctly() -> None:
    report = RecommendationEngine().build((_candle_candidate(),))[0]

    assert report.candle_entry_trigger == Decimal("106.00")
    assert report.candle_stop_level == Decimal("98.00")
    assert report.candle_invalidation_level == Decimal("98.00")
    assert report.entry_price >= report.candle_entry_trigger


def _candidate(
    *,
    symbol: str,
    strategy_score: Decimal,
    probability_score: Decimal,
    market_intelligence_score: Decimal,
    liquidity_score: Decimal,
    risk_score: Decimal,
    retracement_score: Decimal = Decimal("0.50"),
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=strategy_score,
        probability_score=probability_score,
        market_intelligence_score=market_intelligence_score,
        liquidity_score=liquidity_score,
        risk_score=risk_score,
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Strategy Strength",
                score_points=Decimal("8"),
                max_points=Decimal("10"),
                rationale="setup quality is constructive",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Drawdown",
                penalty_points=Decimal("1"),
                rationale="expected drawdown remains controlled",
            ),
        ),
        retracement_score=retracement_score,
    )


def _retracement_candidate(
    *,
    symbol: str = "HEALTHY",
    retracement_score: Decimal = Decimal("0.92"),
    current_price: Decimal = Decimal("104"),
    fibonacci_618: Decimal | None = Decimal("95"),
    fibonacci_786: Decimal | None = Decimal("88"),
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=Decimal("0.82"),
        probability_score=Decimal("0.80"),
        market_intelligence_score=Decimal("0.78"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.82"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Constructive pullback",
                score_points=Decimal("9"),
                max_points=Decimal("10"),
                rationale="Price is holding near short-term support.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Invalidation",
                penalty_points=Decimal("1"),
                rationale="Close below key retracement support weakens the setup.",
            ),
        ),
        retracement_score=retracement_score,
        trend_structure_score=Decimal("0.84"),
        relative_strength_score=Decimal("0.82"),
        volume_confirmation_score=Decimal("0.78"),
        breakout_setup_score=Decimal("0.80"),
        market_regime_score=Decimal("0.86"),
        sector_strength_score=Decimal("0.76"),
        market_regime="BULL",
        current_price=current_price,
        recent_high=Decimal("108"),
        prior_day_high=Decimal("105"),
        reversal_candle_high=Decimal("104.50"),
        retracement_low=Decimal("101"),
        dma_20=Decimal("101"),
        dma_50=Decimal("96"),
        atr=Decimal("2"),
        swing_high=Decimal("112"),
        swing_low=Decimal("88"),
        fibonacci_382=Decimal("100"),
        fibonacci_500=Decimal("98"),
        fibonacci_618=fibonacci_618,
        fibonacci_786=fibonacci_786,
    )


def _evidence_candidate(
    *,
    symbol: str = "EVIDENCE",
    market_regime: str = "BULL",
    setup_type: str | None = "BREAKOUT",
    current_price: Decimal = Decimal("104"),
    dma_20: Decimal = Decimal("101"),
    dma_50: Decimal = Decimal("99"),
    ema_200: Decimal = Decimal("92"),
    strategy_score: Decimal = Decimal("0.82"),
    relative_strength_score: Decimal = Decimal("0.84"),
    volume_confirmation_score: Decimal = Decimal("0.78"),
    breakout_setup_score: Decimal = Decimal("0.80"),
    historical_win_rate: Decimal | None = None,
    historical_average_gain: Decimal | None = None,
    historical_average_loss: Decimal | None = None,
    historical_expected_value: Decimal | None = None,
    historical_average_hold_days: Decimal | None = None,
    metadata: dict[str, str] | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=strategy_score,
        probability_score=Decimal("0.80"),
        market_intelligence_score=Decimal("0.78"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.82"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Technical evidence",
                score_points=Decimal("8"),
                max_points=Decimal("10"),
                rationale="Evidence stack is deterministic.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Signal conflict",
                penalty_points=Decimal("1"),
                rationale="Some technical signals can conflict.",
            ),
        ),
        retracement_score=Decimal("0.74"),
        trend_structure_score=Decimal("0.82"),
        relative_strength_score=relative_strength_score,
        volume_confirmation_score=volume_confirmation_score,
        breakout_setup_score=breakout_setup_score,
        market_regime_score=Decimal("0.80"),
        sector_strength_score=Decimal("0.76"),
        momentum_confirmation_score=Decimal("0.83"),
        market_regime=market_regime,
        setup_type=setup_type,
        current_price=current_price,
        recent_high=Decimal("108"),
        prior_day_high=Decimal("105"),
        retracement_low=Decimal("101"),
        dma_20=dma_20,
        dma_50=dma_50,
        dma_200=Decimal("93"),
        ema_20=Decimal("102"),
        ema_50=Decimal("100"),
        ema_200=ema_200,
        benchmark_relative_strength=relative_strength_score,
        atr=Decimal("2"),
        swing_high=Decimal("112"),
        swing_low=Decimal("88"),
        fibonacci_382=Decimal("100"),
        fibonacci_500=Decimal("98"),
        fibonacci_618=Decimal("95"),
        fibonacci_786=Decimal("88"),
        historical_win_rate=historical_win_rate,
        historical_average_gain=historical_average_gain,
        historical_average_loss=historical_average_loss,
        historical_expected_value=historical_expected_value,
        historical_average_hold_days=historical_average_hold_days,
        metadata=metadata or {},
    )


def _price_volume_candidate(
    *,
    symbol: str = "PVBUY",
    setup_type: str | None = "BREAKOUT",
    current_price: Decimal = Decimal("105"),
    previous_close: Decimal = Decimal("101"),
    support_level: Decimal = Decimal("98"),
    resistance_level: Decimal = Decimal("103"),
    breakout_attempt: bool = True,
    breakdown_attempt: bool = False,
    lower_highs_lower_lows: bool = False,
    volume_dry_up_score: Decimal | None = None,
    breakout_volume_confirmation: Decimal | None = None,
    selloff_volume_penalty: Decimal | None = None,
    metadata: dict[str, str] | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=Decimal("0.84"),
        probability_score=Decimal("0.80"),
        market_intelligence_score=Decimal("0.78"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.80"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Price-volume setup",
                score_points=Decimal("9"),
                max_points=Decimal("10"),
                rationale="Price and volume evidence are aligned.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Volume failure",
                penalty_points=Decimal("1"),
                rationale="Weak volume can invalidate a breakout.",
            ),
        ),
        retracement_score=Decimal("0.74"),
        trend_structure_score=Decimal("0.82"),
        relative_strength_score=Decimal("0.84"),
        volume_confirmation_score=Decimal("0.78"),
        breakout_setup_score=Decimal("0.82"),
        market_regime_score=Decimal("0.80"),
        sector_strength_score=Decimal("0.76"),
        momentum_confirmation_score=Decimal("0.83"),
        market_regime="BULL",
        setup_type=setup_type,
        current_price=current_price,
        previous_close=previous_close,
        open_price=Decimal("100"),
        high_price=Decimal("106"),
        low_price=Decimal("99"),
        support_level=support_level,
        resistance_level=resistance_level,
        recent_high=Decimal("108"),
        prior_day_high=Decimal("104"),
        retracement_low=Decimal("99"),
        dma_20=Decimal("101"),
        dma_50=Decimal("98"),
        dma_200=Decimal("92"),
        ema_20=Decimal("102"),
        ema_50=Decimal("99"),
        ema_200=Decimal("93"),
        atr=Decimal("2"),
        swing_high=Decimal("112"),
        swing_low=Decimal("88"),
        fibonacci_382=Decimal("100"),
        fibonacci_500=Decimal("98"),
        fibonacci_618=Decimal("95"),
        fibonacci_786=Decimal("88"),
        higher_highs_higher_lows=not lower_highs_lower_lows,
        lower_highs_lower_lows=lower_highs_lower_lows,
        breakout_attempt=breakout_attempt,
        breakdown_attempt=breakdown_attempt,
        volume_dry_up_score=volume_dry_up_score,
        breakout_volume_confirmation=breakout_volume_confirmation,
        selloff_volume_penalty=selloff_volume_penalty,
        metadata=metadata or {"volume": "180000", "average_volume": "100000"},
    )


def _candle_candidate(
    *,
    symbol: str = "CANDLE",
    setup_type: str | None = "BREAKOUT",
    open_price: Decimal = Decimal("99"),
    current_price: Decimal = Decimal("105"),
    high_price: Decimal = Decimal("106"),
    low_price: Decimal = Decimal("98"),
    previous_open_price: Decimal = Decimal("104"),
    previous_close: Decimal = Decimal("100"),
    support_level: Decimal = Decimal("99"),
    resistance_level: Decimal = Decimal("103"),
    breakout_attempt: bool = True,
    strategy_score: Decimal = Decimal("0.84"),
    relative_strength_score: Decimal = Decimal("0.84"),
    volume_confirmation_score: Decimal = Decimal("0.78"),
    breakout_setup_score: Decimal = Decimal("0.82"),
    metadata: dict[str, str] | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=strategy_score,
        probability_score=Decimal("0.80"),
        market_intelligence_score=Decimal("0.78"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.80"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Candle confirmation",
                score_points=Decimal("8"),
                max_points=Decimal("10"),
                rationale="Candlestick evidence is evaluated in context.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Candle failure",
                penalty_points=Decimal("1"),
                rationale="Candle confirmation can fail without volume.",
            ),
        ),
        retracement_score=Decimal("0.74"),
        trend_structure_score=Decimal("0.82"),
        relative_strength_score=relative_strength_score,
        volume_confirmation_score=volume_confirmation_score,
        breakout_setup_score=breakout_setup_score,
        market_regime_score=Decimal("0.80"),
        sector_strength_score=Decimal("0.76"),
        momentum_confirmation_score=Decimal("0.83"),
        market_regime="BULL",
        setup_type=setup_type,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        current_price=current_price,
        previous_open_price=previous_open_price,
        previous_high_price=max(previous_open_price, previous_close) + Decimal("1"),
        previous_low_price=min(previous_open_price, previous_close) - Decimal("1"),
        previous_close=previous_close,
        support_level=support_level,
        resistance_level=resistance_level,
        recent_high=Decimal("108"),
        prior_day_high=Decimal("104"),
        reversal_candle_high=high_price,
        retracement_low=low_price,
        dma_20=Decimal("101"),
        dma_50=Decimal("98"),
        dma_200=Decimal("92"),
        ema_20=Decimal("102"),
        ema_50=Decimal("99"),
        ema_200=Decimal("93"),
        atr=Decimal("2"),
        swing_high=Decimal("112"),
        swing_low=Decimal("88"),
        fibonacci_382=Decimal("100"),
        fibonacci_500=Decimal("98"),
        fibonacci_618=Decimal("95"),
        fibonacci_786=Decimal("88"),
        higher_highs_higher_lows=True,
        breakout_attempt=breakout_attempt,
        metadata=metadata or {"volume": "180000", "average_volume": "100000"},
    )


def _history_candidate(
    *,
    symbol: str = "HISTORY",
    setup_type: str = "BREAKOUT",
    breakout_attempt: bool = True,
    resistance_level: Decimal = Decimal("160"),
    prior_day_high: Decimal = Decimal("158"),
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=Decimal("0.88"),
        probability_score=Decimal("0.82"),
        market_intelligence_score=Decimal("0.80"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.82"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="History-backed setup",
                score_points=Decimal("9"),
                max_points=Decimal("10"),
                rationale="Trade levels are derived from deterministic OHLCV bars.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Execution risk",
                penalty_points=Decimal("1"),
                rationale="Stops and targets depend on market structure.",
            ),
        ),
        price_history=_rising_history(),
        retracement_score=Decimal("0.82"),
        trend_structure_score=Decimal("0.86"),
        relative_strength_score=Decimal("0.84"),
        volume_confirmation_score=Decimal("0.82"),
        breakout_setup_score=Decimal("0.86"),
        market_regime_score=Decimal("0.82"),
        sector_strength_score=Decimal("0.78"),
        momentum_confirmation_score=Decimal("0.83"),
        setup_type=setup_type,
        market_regime="BULL",
        open_price=Decimal("157"),
        high_price=Decimal("160"),
        low_price=Decimal("156"),
        current_price=Decimal("159"),
        resistance_level=resistance_level,
        prior_day_high=prior_day_high,
        breakout_attempt=breakout_attempt,
        higher_highs_higher_lows=True,
        breakout_volume_confirmation=Decimal("0.90"),
        metadata={"volume": "180000", "average_volume": "100000"},
    )


def _rising_history() -> tuple[OHLCVBar, ...]:
    return tuple(
        OHLCVBar(
            observed_on=date.fromordinal(date(2026, 5, 9).toordinal() + offset),
            open_price=Decimal(99 + offset),
            high_price=Decimal(102 + offset),
            low_price=Decimal(98 + offset),
            close_price=Decimal(100 + offset),
            volume=Decimal("100000") + Decimal(offset * 1000),
        )
        for offset in range(60)
    )


def _engulfing_history_candidate() -> RecommendationCandidate:
    history = (
        OHLCVBar(
            observed_on=date(2026, 7, 5),
            open_price=Decimal("106"),
            high_price=Decimal("107"),
            low_price=Decimal("101"),
            close_price=Decimal("103"),
            volume=Decimal("100000"),
        ),
        OHLCVBar(
            observed_on=date(2026, 7, 6),
            open_price=Decimal("104"),
            high_price=Decimal("105"),
            low_price=Decimal("100"),
            close_price=Decimal("101"),
            volume=Decimal("100000"),
        ),
        OHLCVBar(
            observed_on=date(2026, 7, 7),
            open_price=Decimal("100"),
            high_price=Decimal("112"),
            low_price=Decimal("98"),
            close_price=Decimal("110"),
            volume=Decimal("180000"),
        ),
    )
    return RecommendationCandidate(
        symbol="ENGULF",
        observed_on=date(2026, 7, 7),
        action=RecommendationAction.BUY,
        strategy_score=Decimal("0.84"),
        probability_score=Decimal("0.80"),
        market_intelligence_score=Decimal("0.78"),
        liquidity_score=Decimal("0.76"),
        risk_score=Decimal("0.80"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("30"),
        evidence=(
            RecommendationEvidence(
                label="Candle history",
                score_points=Decimal("8"),
                max_points=Decimal("10"),
                rationale="Candle pattern should hydrate from OHLC history.",
            ),
        ),
        price_history=history,
        retracement_score=Decimal("0.74"),
        trend_structure_score=Decimal("0.82"),
        relative_strength_score=Decimal("0.84"),
        volume_confirmation_score=Decimal("0.78"),
        breakout_setup_score=Decimal("0.82"),
        market_regime_score=Decimal("0.80"),
        sector_strength_score=Decimal("0.76"),
        momentum_confirmation_score=Decimal("0.83"),
        setup_type="PULLBACK",
        market_regime="BULL",
        support_level=Decimal("99"),
        resistance_level=Decimal("112"),
        breakout_volume_confirmation=Decimal("0.80"),
        metadata={"volume": "180000", "average_volume": "100000"},
    )
