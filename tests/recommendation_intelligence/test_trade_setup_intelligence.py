from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from alpha.application.intelligence import (
    _entry_trigger_text,
    _next_trigger_text,
    _recommendation_detail_lines,
)
from alpha.recommendation_intelligence import (
    CandlePatternEngine,
    EdgeConfidence,
    EntryTriggerStyle,
    EvidenceScoringEngine,
    OHLCVBar,
    PriceVolumeSignalEngine,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationEngine,
    RecommendationEvidence,
    StrategyQuality,
    TradeSetupAssessment,
    TradeSetupEngine,
    TradeStrategyAction,
    TradeStrategyType,
    TriggerStatus,
)


def test_bull_flag_setup_is_detected_ready_and_buy_mapped() -> None:
    candidate = _candidate(setup_type="BULL_FLAG", current_price=Decimal("106"))

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "BULL FLAG"
    assert setup.setup_category == "TREND CONTINUATION"
    assert setup.setup_quality in {"A+", "A", "B"}
    assert setup.setup_stage == "ENTRY_READY"
    assert setup.entry_ready is True
    assert report.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    assert report.entry_zone_low == setup.aggressive_entry
    assert report.entry_zone_high == setup.preferred_entry
    assert report.entry_price == setup.confirmation_entry
    assert report.initial_stop_loss == setup.initial_stop
    assert report.final_signal in {"BUY", "STRONG_BUY"}


def test_confirmed_buy_generates_multiple_trade_strategy_playbooks() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    strategy_types = {strategy.strategy_type for strategy in report.trade_strategies}

    assert TradeStrategyType.MOMENTUM_BREAKOUT in strategy_types
    assert TradeStrategyType.PULLBACK_ENTRY in strategy_types
    assert TradeStrategyType.AGGRESSIVE_ACCUMULATION in strategy_types
    assert len(report.trade_strategies) >= 3


def test_momentum_breakout_strategy_can_be_buy_now_when_confirmed() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    breakout = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.MOMENTUM_BREAKOUT
    )

    assert breakout.action is TradeStrategyAction.BUY_NOW
    assert breakout.trigger_text == "Already confirmed."
    assert breakout.stop_loss == report.initial_stop_loss
    assert "closing basis" in breakout.stop_rule
    assert "20-DMA" not in breakout.stop_rule


def test_pullback_and_aggressive_strategies_are_waiting_playbooks() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    pullback = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.PULLBACK_ENTRY
    )
    aggressive = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.AGGRESSIVE_ACCUMULATION
    )
    breakout = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.MOMENTUM_BREAKOUT
    )

    assert pullback.action is TradeStrategyAction.WAIT_FOR_PULLBACK
    assert aggressive.action is TradeStrategyAction.WAIT_FOR_DEEP_PULLBACK
    assert aggressive.position_size_multiplier < breakout.position_size_multiplier
    assert "Better risk/reward" in pullback.explanation
    assert "lower fill probability" in pullback.explanation


def test_strategy_rank_and_edge_stats_are_separate_from_fill_probability() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                setup_type="BULL_FLAG",
                current_price=Decimal("106"),
                price_history=_price_history(80),
            ),
        )
    )[0]

    pullback = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.PULLBACK_ENTRY
    )

    assert pullback.strategy_rank.label == "#1 Recommended"
    assert pullback.strategy_rank.quality in {
        StrategyQuality.EXCELLENT,
        StrategyQuality.GOOD,
    }
    assert pullback.edge_stats is not None
    assert pullback.edge_stats.confidence is EdgeConfidence.INSUFFICIENT_DATA
    assert pullback.edge_stats.target_1_hit_rate is None
    assert pullback.edge_stats.fill_probability is not None
    assert pullback.expected_wait_days == 10


def test_insufficient_historical_edge_renders_fetch_attempt_context() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    lines = _recommendation_detail_lines(1, report)

    assert any("Status: Not yet computed" in line for line in lines)
    assert any("Dataset Source: local historical bars" in line for line in lines)
    assert any("Archive Fetch Status:" in line for line in lines)


def test_statistical_edge_computes_rates_from_actual_matched_samples() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                setup_type="BULL_FLAG",
                current_price=Decimal("106"),
                price_history=_price_history(140),
            ),
        )
    )[0]
    breakout = next(
        strategy
        for strategy in report.trade_strategies
        if strategy.strategy_type is TradeStrategyType.MOMENTUM_BREAKOUT
    )

    assert breakout.edge_stats is not None
    assert breakout.edge_stats.sample_size >= 30
    assert breakout.edge_stats.target_1_hit_rate is not None
    assert breakout.edge_stats.stop_loss_hit_rate is not None


def test_entry_ready_buy_renders_confirmed_trigger_without_wait_language() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    lines = _recommendation_detail_lines(1, report)
    next_trigger = next(line for line in lines if "Next Trigger:" in line)
    instruction = next(line for line in lines if "Entry Instruction:" in line)

    assert report.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    assert "Next Trigger: Already confirmed." in next_trigger
    assert "Buy only after" not in next_trigger
    assert "Daily close above" not in next_trigger
    assert "Buy within the entry zone" in instruction


def test_ema_pullback_setup_uses_support_entry_and_can_be_ready() -> None:
    candidate = _candidate(
        setup_type="EMA_PULLBACK",
        current_price=Decimal("103"),
        resistance_level=Decimal("102"),
        retracement_score=Decimal("0.88"),
        volume_dry_up_score=Decimal("0.78"),
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "EMA PULLBACK"
    assert setup.setup_stage == "ENTRY_READY"
    assert setup.entry_ready is True
    assert setup.preferred_entry == Decimal("104.00")
    assert setup.initial_stop is not None
    assert report.target_1 == setup.partial_exit
    assert report.target_2 == setup.final_exit
    assert report.target_3 is not None
    assert report.risk_reward_ratio is not None
    assert report.final_signal in {"BUY", "STRONG_BUY"}


def test_vcp_setup_detects_watchlist_when_not_entry_ready() -> None:
    candidate = _candidate(
        setup_type="VCP",
        current_price=Decimal("100"),
        resistance_level=Decimal("106"),
        volatility_expansion_score=Decimal("0.80"),
        volume_dry_up_score=Decimal("0.86"),
        metadata={"volume": "90000", "average_volume": "100000"},
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "VOLATILITY CONTRACTION PATTERN"
    assert setup.setup_category == "BREAKOUT"
    assert setup.setup_stage == "READY_FOR_CONFIRMATION"
    assert setup.entry_ready is False
    assert report.trigger_status is TriggerStatus.WAITING_FOR_VOLUME_CONFIRMATION
    assert report.final_signal == "WATCHLIST"
    assert any("Why BUY became WATCHLIST" in line for line in report.explanation)


def test_watchlist_renders_wait_trigger_and_zero_allocation_status() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                setup_type="VCP",
                current_price=Decimal("100"),
                resistance_level=Decimal("106"),
                volatility_expansion_score=Decimal("0.80"),
                volume_dry_up_score=Decimal("0.86"),
                metadata={"volume": "90000", "average_volume": "100000"},
            ),
        )
    )[0]

    lines = _recommendation_detail_lines(1, report)

    assert report.final_signal == "WATCHLIST"
    assert any("Execution Status: WAIT FOR CONFIRMATION" in line for line in lines)
    assert any(
        "Portfolio Allocation: NO ALLOCATION — waiting for confirmation" in line
        for line in lines
    )
    assert any("Next Trigger: Buy only after" in line for line in lines)
    assert any("Entry Instruction: Wait. Do not enter yet." in line for line in lines)


def test_cup_and_handle_setup_is_detected_as_breakout_watchlist() -> None:
    candidate = _candidate(
        setup_type="CUP_HANDLE",
        current_price=Decimal("101"),
        resistance_level=Decimal("106"),
        volume_dry_up_score=Decimal("0.74"),
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "CUP & HANDLE"
    assert setup.setup_category == "BREAKOUT"
    assert setup.entry_ready is False
    assert report.final_signal == "WATCHLIST"


def test_flat_base_setup_is_detected_ready_with_confirmation_entry() -> None:
    candidate = _candidate(
        setup_type="FLAT_BASE",
        current_price=Decimal("107"),
        resistance_level=Decimal("105"),
        breakout_attempt=True,
    )

    setup = _setup(candidate)

    assert setup.setup_name == "FLAT BASE"
    assert setup.setup_stage == "ENTRY_READY"
    assert setup.entry_ready is True
    assert setup.confirmation_entry == Decimal("108.00")
    assert setup.maximum_chase_price == Decimal("109.00")


def test_failed_breakout_setup_maps_to_avoid() -> None:
    candidate = _candidate(
        setup_type="FAILED_BREAKOUT",
        current_price=Decimal("100"),
        resistance_level=Decimal("105"),
        breakout_attempt=True,
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "FAILED BREAKOUT"
    assert setup.setup_quality == "REJECT"
    assert setup.setup_stage == "INVALID"
    assert setup.entry_ready is False
    assert report.trigger_status is TriggerStatus.INVALID_OR_NOT_ACTIONABLE
    assert report.final_signal == "AVOID"


def test_avoid_and_sell_generate_only_no_trade_playbooks() -> None:
    avoid = RecommendationEngine().build(
        (
            _candidate(
                setup_type="FAILED_BREAKOUT",
                current_price=Decimal("100"),
                resistance_level=Decimal("105"),
                breakout_attempt=True,
            ),
        )
    )[0]
    sell = RecommendationEngine().build(
        (
            _candidate(
                setup_type="TREND_FAILURE",
                current_price=Decimal("94"),
                dma_20=Decimal("101"),
                dma_50=Decimal("99"),
                lower_highs_lower_lows=True,
                metadata={"volume": "200000", "average_volume": "100000"},
            ),
        )
    )[0]

    for report in (avoid, sell):
        assert len(report.trade_strategies) == 1
        assert report.trade_strategies[0].strategy_type is TradeStrategyType.NO_TRADE
        assert report.trade_strategies[0].action is TradeStrategyAction.AVOID


def test_avoid_renders_exit_action_and_reentry_watch_level() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                setup_type="FAILED_BREAKOUT",
                current_price=Decimal("100"),
                resistance_level=Decimal("105"),
                breakout_attempt=True,
            ),
        )
    )[0]

    lines = _recommendation_detail_lines(1, report)

    assert any("Next Trigger: Action: Avoid / Exit." in line for line in lines)
    assert any("Entry Instruction: Avoid / Exit." in line for line in lines)
    assert any("Re-entry Watch Level:" in line for line in lines)
    assert any("only if setup improves" in line for line in lines)


def test_setup_entry_values_populate_trade_plan_entry_zone_and_trigger() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="FLAT_BASE", current_price=Decimal("107")),)
    )[0]

    assert report.entry_zone_low == report.trade_plan.aggressive_entry
    assert report.entry_zone_high == report.trade_plan.preferred_entry
    assert report.entry_price == report.trade_plan.confirmation_entry
    assert report.entry_price is not None


def test_setup_exit_values_populate_targets_and_risk_reward() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    assert report.initial_stop_loss is not None
    assert report.initial_stop_loss < report.entry_price
    assert report.target_1 == report.trade_plan.partial_exit
    assert report.target_2 == report.trade_plan.final_exit
    assert report.target_3 is not None
    assert report.risk_reward_ratio is not None


def test_ready_for_confirmation_implies_not_entry_ready() -> None:
    setup = _setup(
        _candidate(
            setup_type="VCP",
            current_price=Decimal("100"),
            resistance_level=Decimal("106"),
            volatility_expansion_score=Decimal("0.80"),
            volume_dry_up_score=Decimal("0.86"),
            metadata={"volume": "90000", "average_volume": "100000"},
        )
    )

    assert setup.setup_stage == "READY_FOR_CONFIRMATION"
    assert setup.entry_ready is False


def test_cli_detail_lines_render_trade_strategy_values() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    lines = _recommendation_detail_lines(1, report)
    entry = next(line for line in lines if "Entry:" in line)
    trigger = next(line for line in lines if "      Trigger:" in line)
    stop = next(line for line in lines if "Risk Stop:" in line)
    targets = next(line for line in lines if "Targets:" in line)
    risk_reward = next(line for line in lines if "Risk / Reward:" in line)
    current_rr = next(
        line for line in lines if "Current Market R/R to Target 1:" in line
    )

    assert any("Trade Strategies:" in line for line in lines)
    assert any("Momentum Breakout" in line for line in lines)
    assert any("Pullback Entry" in line for line in lines)
    assert report.current_market_price == Decimal("106")
    assert report.current_market_risk_reward_ratio is not None
    assert "unavailable" not in entry
    assert "unavailable" not in trigger
    assert "unavailable" not in stop
    assert "unavailable" not in targets
    assert "unavailable" not in risk_reward
    assert "unavailable" not in current_rr
    assert any("Stage: Entry Ready" in line for line in lines)
    assert any("Entry Ready: Yes" in line for line in lines)


def test_cli_detail_lines_render_trade_support_and_risk_reasons() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    lines = _recommendation_detail_lines(1, report)
    support_index = lines.index("   Why It May Work:")
    risk_index = lines.index("   Why It May Fail:")

    assert support_index < risk_index
    assert lines[support_index + 1].startswith("   - ")
    assert lines[risk_index + 1].startswith("   - ")
    assert any(
        "Current market price" in line for line in lines[support_index:risk_index]
    )
    assert any("20-DMA" in line for line in lines[support_index:risk_index])
    assert not any(
        line.endswith("Trend is strong uptrend.")
        for line in lines[support_index:risk_index]
    )
    assert any("insufficient" in line.lower() for line in lines[risk_index:])


def test_current_market_risk_reward_is_unavailable_for_avoid() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="FAILED_BREAKOUT", current_price=Decimal("100")),)
    )[0]

    assert report.final_signal == "AVOID"
    assert report.current_market_risk_reward_ratio is None


def test_entry_trigger_is_never_rendered_as_only_a_number() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="FLAT_BASE", current_price=Decimal("107")),)
    )[0]

    trigger_line = next(
        line
        for line in _recommendation_detail_lines(1, report)
        if "      Trigger:" in line
    )

    assert trigger_line != f"      Trigger: ₹{report.entry_price}"
    assert (
        "above" in trigger_line.lower()
        or "zone" in trigger_line.lower()
        or "already confirmed" in trigger_line.lower()
    )


def test_strategy_output_keeps_20_dma_as_reference_not_second_active_stop() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="BULL_FLAG", current_price=Decimal("106")),)
    )[0]

    lines = _recommendation_detail_lines(1, report)
    risk_stop_lines = tuple(line for line in lines if "Risk Stop:" in line)
    reference_lines = tuple(line for line in lines if "Trend Reference:" in line)

    assert risk_stop_lines
    assert all("20-DMA" not in line for line in risk_stop_lines)
    assert reference_lines
    assert any("20-DMA" in line for line in reference_lines)
    assert all("not an active stop" in line for line in reference_lines)
    assert all("Active Exit Rule" not in line for line in lines)


def test_confirmed_next_trigger_is_not_rendered_as_only_a_number() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="FLAT_BASE", current_price=Decimal("107")),)
    )[0]

    assert _next_trigger_text(report) == "Already confirmed."


def test_close_above_trigger_renders_daily_close_language() -> None:
    report = _report_with_trigger_style(EntryTriggerStyle.CLOSE_ABOVE)

    assert "Daily close above" in _entry_trigger_text(report)


def test_cross_above_trigger_renders_intraday_cross_language() -> None:
    report = _report_with_trigger_style(EntryTriggerStyle.CROSS_ABOVE)

    assert "crosses above" in _entry_trigger_text(report)


def test_breakout_with_volume_trigger_renders_volume_condition() -> None:
    report = _report_with_trigger_style(EntryTriggerStyle.BREAKOUT_WITH_VOLUME)

    trigger_text = _entry_trigger_text(report)

    assert "Breakout above" in trigger_text
    assert "volume at least 1.5x" in trigger_text


def test_cli_strategy_reference_includes_actual_20_dma_value() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="EMA_PULLBACK", current_price=Decimal("103")),)
    )[0]

    invalidation = next(
        line
        for line in _recommendation_detail_lines(1, report)
        if "Trend Reference:" in line
    )

    assert "20-DMA" in invalidation
    assert "₹101.00" in invalidation


def test_holding_period_appears_in_final_output() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="MOMENTUM_CONTINUATION"),)
    )[0]

    lines = _recommendation_detail_lines(1, report)

    assert any("Holding Period: 5-15 trading days" in line for line in lines)


def test_cup_and_handle_holding_period_uses_longer_default() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="CUP_HANDLE", current_price=Decimal("101")),)
    )[0]

    assert report.trade_plan.expected_holding_period == "20-60 trading days"


def test_failed_breakout_holding_period_is_exit_avoid() -> None:
    report = RecommendationEngine().build(
        (_candidate(setup_type="FAILED_BREAKOUT", current_price=Decimal("100")),)
    )[0]

    assert report.trade_plan.expected_holding_period == "exit / avoid immediately"


def test_no_valid_setup_holding_period_is_unavailable() -> None:
    report = RecommendationEngine().build(
        (
            _candidate(
                setup_type="WEAK_RANDOM",
                strategy_score=Decimal("0.30"),
                breakout_setup_score=Decimal("0.25"),
                relative_strength_score=Decimal("0.35"),
                volume_confirmation_score=Decimal("0.35"),
                current_price=Decimal("100"),
                metadata={"volume": "90000", "average_volume": "100000"},
            ),
        )
    )[0]

    assert report.trade_plan.expected_holding_period == "unavailable"


def _report_with_trigger_style(style: EntryTriggerStyle):
    report = RecommendationEngine().build(
        (_candidate(setup_type="FLAT_BASE", current_price=Decimal("107")),)
    )[0]
    trade_plan = replace(report.trade_plan, entry_trigger_style=style)
    return replace(report, trade_plan=trade_plan)


def test_trend_failure_setup_maps_to_sell() -> None:
    candidate = _candidate(
        setup_type="TREND_FAILURE",
        current_price=Decimal("94"),
        dma_20=Decimal("101"),
        dma_50=Decimal("99"),
        lower_highs_lower_lows=True,
        metadata={"volume": "200000", "average_volume": "100000"},
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "TREND FAILURE"
    assert setup.setup_category == "BEARISH"
    assert setup.setup_stage == "INVALID"
    assert report.final_signal == "SELL"


def test_no_valid_setup_maps_to_avoid() -> None:
    candidate = _candidate(
        setup_type="WEAK_RANDOM",
        strategy_score=Decimal("0.30"),
        breakout_setup_score=Decimal("0.25"),
        relative_strength_score=Decimal("0.35"),
        volume_confirmation_score=Decimal("0.35"),
        current_price=Decimal("100"),
        metadata={"volume": "90000", "average_volume": "100000"},
    )

    setup = _setup(candidate)
    report = RecommendationEngine().build((candidate,))[0]

    assert setup.setup_name == "NO VALID SETUP"
    assert setup.setup_quality == "REJECT"
    assert setup.entry_ready is False
    assert report.final_signal == "AVOID"


def _setup(candidate: RecommendationCandidate) -> TradeSetupAssessment:
    price_volume = PriceVolumeSignalEngine().assess(candidate)
    candle = CandlePatternEngine().assess(
        candidate=candidate,
        price_volume=price_volume,
    )
    evidence = EvidenceScoringEngine().assess(candidate, price_volume, candle)
    return TradeSetupEngine().assess(
        candidate=candidate,
        price_volume=price_volume,
        candle_pattern=candle,
        evidence_assessment=evidence,
    )


def _candidate(
    *,
    setup_type: str,
    current_price: Decimal = Decimal("106"),
    support_level: Decimal = Decimal("101"),
    resistance_level: Decimal = Decimal("105"),
    dma_20: Decimal = Decimal("101"),
    dma_50: Decimal = Decimal("98"),
    retracement_score: Decimal = Decimal("0.78"),
    strategy_score: Decimal = Decimal("0.88"),
    breakout_setup_score: Decimal = Decimal("0.86"),
    relative_strength_score: Decimal = Decimal("0.87"),
    volume_confirmation_score: Decimal = Decimal("0.84"),
    volume_dry_up_score: Decimal = Decimal("0.68"),
    volatility_expansion_score: Decimal = Decimal("0.70"),
    breakout_attempt: bool = False,
    lower_highs_lower_lows: bool = False,
    price_history: tuple[OHLCVBar, ...] = (),
    metadata: dict[str, str] | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol="SETUP",
        observed_on=date(2026, 7, 9),
        action=RecommendationAction.BUY,
        strategy_score=strategy_score,
        probability_score=Decimal("0.84"),
        market_intelligence_score=Decimal("0.82"),
        liquidity_score=Decimal("0.80"),
        risk_score=Decimal("0.82"),
        expected_return=Decimal("0.14"),
        expected_drawdown=Decimal("0.04"),
        expected_holding_period_days=Decimal("18"),
        evidence=(
            RecommendationEvidence(
                label="Setup evidence",
                score_points=Decimal("9"),
                max_points=Decimal("10"),
                rationale="Price-volume setup evidence is constructive.",
            ),
        ),
        metadata=metadata or {"volume": "180000", "average_volume": "100000"},
        retracement_score=retracement_score,
        trend_structure_score=Decimal("0.86"),
        relative_strength_score=relative_strength_score,
        volume_confirmation_score=volume_confirmation_score,
        breakout_setup_score=breakout_setup_score,
        market_regime_score=Decimal("0.84"),
        sector_strength_score=Decimal("0.80"),
        momentum_confirmation_score=Decimal("0.86"),
        price_structure_score=Decimal("0.86"),
        volume_dry_up_score=volume_dry_up_score,
        volatility_expansion_score=volatility_expansion_score,
        breakout_volume_confirmation=Decimal("0.90"),
        market_regime="BULL",
        setup_type=setup_type,
        open_price=current_price - Decimal("2"),
        high_price=current_price + Decimal("1"),
        low_price=current_price - Decimal("3"),
        current_price=current_price,
        previous_open_price=current_price - Decimal("3"),
        previous_high_price=current_price,
        previous_low_price=current_price - Decimal("4"),
        previous_close=current_price - Decimal("2"),
        support_level=support_level,
        resistance_level=resistance_level,
        recent_high=resistance_level + Decimal("3"),
        prior_day_high=current_price,
        reversal_candle_high=current_price,
        retracement_low=support_level,
        dma_20=dma_20,
        dma_50=dma_50,
        dma_200=Decimal("90"),
        ema_20=dma_20,
        ema_50=dma_50,
        ema_200=Decimal("91"),
        atr=Decimal("2"),
        swing_high=Decimal("112"),
        swing_low=Decimal("88"),
        fibonacci_382=Decimal("103"),
        fibonacci_500=Decimal("100"),
        fibonacci_618=Decimal("97"),
        fibonacci_786=Decimal("93"),
        higher_highs_higher_lows=not lower_highs_lower_lows,
        lower_highs_lower_lows=lower_highs_lower_lows,
        breakout_attempt=breakout_attempt,
        price_history=price_history,
    )


def _price_history(length: int) -> tuple[OHLCVBar, ...]:
    start = date(2026, 1, 1)
    return tuple(
        OHLCVBar(
            observed_on=start + timedelta(days=index),
            open_price=Decimal("80") + Decimal(index) * Decimal("0.20"),
            high_price=Decimal("82") + Decimal(index) * Decimal("0.20"),
            low_price=Decimal("79") + Decimal(index) * Decimal("0.20"),
            close_price=Decimal("81") + Decimal(index) * Decimal("0.20"),
            volume=Decimal("100000") + Decimal(index),
        )
        for index in range(length)
    )
