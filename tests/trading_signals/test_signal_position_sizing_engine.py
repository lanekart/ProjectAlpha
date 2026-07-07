from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import SignalSide
from alpha.trading_signals.ensemble import (
    EnsembleDecisionReport,
    TradeRecommendation,
)
from alpha.trading_signals.position_sizing import (
    PositionSizingConfig,
    RecommendationPositionSizer,
    SizedTradeRecommendation,
    TradePlan,
)


def test_position_sizer_allocates_buy_trades_by_recommendation_score() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(
                symbol="TCS",
                action=SignalSide.BUY,
                score=Decimal("0.80"),
            ),
            _recommendation(
                symbol="INFY",
                action=SignalSide.BUY,
                score=Decimal("0.40"),
            ),
        ),
    )
    sizer = RecommendationPositionSizer(
        config=PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
            cash_reserve_weight=Decimal("0.10"),
            max_position_weight=Decimal("0.50"),
            minimum_recommendation_score=Decimal("0.10"),
        )
    )

    plan = sizer.size(
        report=report,
        prices={
            "TCS": Decimal("1000"),
            "INFY": Decimal("500"),
        },
    )

    assert plan.generated_for == date(2026, 1, 10)
    assert plan.trade_count == 2
    assert plan.get("TCS").target_weight == Decimal("0.5000000000000000000000000000")
    assert plan.get("TCS").quantity == 500
    assert plan.get("TCS").target_notional == Decimal("500000")
    assert plan.get("INFY").target_weight == Decimal("0.3000000000000000000000000000")
    assert plan.get("INFY").quantity == 600
    assert plan.gross_buy_notional == Decimal("800000")


def test_position_sizer_ignores_low_score_buy_recommendations() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(
                symbol="TCS",
                action=SignalSide.BUY,
                score=Decimal("0.54"),
            ),
        ),
    )
    sizer = RecommendationPositionSizer(
        config=PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
            minimum_recommendation_score=Decimal("0.55"),
        )
    )

    plan = sizer.size(
        report=report,
        prices={"TCS": Decimal("1000")},
    )

    assert plan.trade_count == 0
    assert plan.gross_buy_notional == Decimal("0")


def test_position_sizer_creates_sell_trade_only_for_current_holdings() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(
                symbol="TCS",
                action=SignalSide.SELL,
                score=Decimal("0.70"),
            ),
            _recommendation(
                symbol="INFY",
                action=SignalSide.SELL,
                score=Decimal("0.90"),
            ),
        ),
    )
    sizer = RecommendationPositionSizer(
        config=PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
        )
    )

    plan = sizer.size(
        report=report,
        prices={
            "TCS": Decimal("1000"),
            "INFY": Decimal("500"),
        },
        current_positions={"TCS": 25},
    )

    assert plan.trade_count == 1
    assert plan.get("TCS").action is SignalSide.SELL
    assert plan.get("TCS").quantity == -25
    assert plan.get("TCS").target_notional == Decimal("25000")
    assert plan.gross_sell_notional == Decimal("25000")


def test_position_sizer_respects_lot_size() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(
                symbol="TCS",
                action=SignalSide.BUY,
                score=Decimal("1"),
            ),
        ),
    )
    sizer = RecommendationPositionSizer(
        config=PositionSizingConfig(
            portfolio_value=Decimal("100000"),
            cash_reserve_weight=Decimal("0"),
            max_position_weight=Decimal("1"),
            lot_size=25,
        )
    )

    plan = sizer.size(
        report=report,
        prices={"TCS": Decimal("300")},
    )

    assert plan.get("TCS").quantity == 325
    assert plan.get("TCS").target_notional == Decimal("97500")


def test_trade_plan_sorts_sells_before_buys() -> None:
    plan = TradePlan(
        generated_for=date(2026, 1, 10),
        portfolio_value=Decimal("1000000"),
        cash_reserve_weight=Decimal("0.10"),
        trades=(
            _sized_trade(symbol="TCS", action=SignalSide.BUY),
            _sized_trade(symbol="INFY", action=SignalSide.SELL),
        ),
    )

    assert tuple(trade.symbol for trade in plan.trades) == (
        "INFY",
        "TCS",
    )
    assert tuple(trade.symbol for trade in plan.actionable) == (
        "INFY",
        "TCS",
    )


def test_position_sizing_config_validates_constraints() -> None:
    with pytest.raises(ValueError, match="portfolio value"):
        PositionSizingConfig(portfolio_value=Decimal("0"))

    with pytest.raises(ValueError, match="cash reserve"):
        PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
            cash_reserve_weight=Decimal("1"),
        )

    with pytest.raises(ValueError, match="lot size"):
        PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
            lot_size=0,
        )


def test_position_sizer_validates_prices() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(
                symbol="TCS",
                action=SignalSide.BUY,
                score=Decimal("1"),
            ),
        ),
    )
    sizer = RecommendationPositionSizer(
        config=PositionSizingConfig(
            portfolio_value=Decimal("1000000"),
        )
    )

    with pytest.raises(ValueError, match="prices"):
        sizer.size(
            report=report,
            prices={"TCS": Decimal("0")},
        )


def _recommendation(
    *,
    symbol: str,
    action: SignalSide,
    score: Decimal,
) -> TradeRecommendation:
    return TradeRecommendation(
        symbol=symbol,
        action=action,
        confidence=score,
        score=score,
        supporting_strategies=("momentum",),
        opposing_strategies=(),
        neutral_strategies=(),
        reasons=("test recommendation",),
        agreement_score=score,
        strategy_quality_score=score,
        signal_confidence_score=score,
        coverage_score=score,
        recommendation_score=score,
    )


def _sized_trade(
    *,
    symbol: str,
    action: SignalSide,
) -> SizedTradeRecommendation:
    quantity = 10
    if action is SignalSide.SELL:
        quantity = -10
    return SizedTradeRecommendation(
        symbol=symbol,
        action=action,
        recommendation_score=Decimal("1"),
        target_weight=Decimal("0.10"),
        target_notional=Decimal("100000"),
        estimated_price=Decimal("1000"),
        quantity=quantity,
        reasons=("test trade",),
    )
