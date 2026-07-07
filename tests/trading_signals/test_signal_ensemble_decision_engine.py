from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import SignalBatch, SignalSide, TradingSignal
from alpha.trading_signals.ensemble import (
    EnsembleDecisionEngine,
    EnsembleDecisionReport,
    TradeRecommendation,
)
from alpha.trading_signals.ranking import RankedStrategy, StrategyRankingReport


def test_ensemble_decision_engine_builds_weighted_buy_recommendation() -> None:
    report = EnsembleDecisionEngine().decide(
        ranking=_ranking(),
        batches=(
            _batch(strategy="momentum", side=SignalSide.BUY),
            _batch(strategy="breakout", side=SignalSide.BUY),
            _batch(strategy="mean_reversion", side=SignalSide.SELL),
        ),
    )

    recommendation = report.get("TCS")

    assert report.generated_for == date(2026, 1, 10)
    assert recommendation.action is SignalSide.BUY
    assert recommendation.is_actionable is True
    assert recommendation.supporting_strategies == (
        "breakout",
        "momentum",
    )
    assert recommendation.opposing_strategies == ("mean_reversion",)
    assert recommendation.neutral_strategies == ()
    assert recommendation.agreement_score == Decimal("0.6666666666666666666666666667")
    assert recommendation.strategy_quality_score == Decimal("0.5")
    assert recommendation.signal_confidence_score == Decimal("1")
    assert recommendation.coverage_score == Decimal("0.6666666666666666666666666667")
    assert recommendation.recommendation_score == Decimal(
        "0.6750000000000000000000000000"
    )
    assert recommendation.confidence == recommendation.recommendation_score


def test_ensemble_decision_engine_respects_higher_quality_sell_weight() -> None:
    report = EnsembleDecisionEngine().decide(
        ranking=StrategyRankingReport(
            ranked=(
                _ranked_strategy(
                    rank=1,
                    strategy="mean_reversion",
                    score=Decimal("0.95"),
                ),
                _ranked_strategy(
                    rank=2,
                    strategy="momentum",
                    score=Decimal("0.30"),
                ),
                _ranked_strategy(
                    rank=3,
                    strategy="breakout",
                    score=Decimal("0.30"),
                ),
            )
        ),
        batches=(
            _batch(strategy="momentum", side=SignalSide.BUY),
            _batch(strategy="breakout", side=SignalSide.BUY),
            _batch(strategy="mean_reversion", side=SignalSide.SELL),
        ),
    )

    recommendation = report.get("TCS")

    assert recommendation.action is SignalSide.SELL
    assert recommendation.supporting_strategies == ("mean_reversion",)
    assert recommendation.opposing_strategies == (
        "breakout",
        "momentum",
    )
    assert recommendation.strategy_quality_score == Decimal("0.95")


def test_ensemble_decision_engine_builds_sell_recommendation() -> None:
    report = EnsembleDecisionEngine().decide(
        ranking=_ranking(),
        batches=(
            _batch(strategy="momentum", side=SignalSide.SELL),
            _batch(strategy="breakout", side=SignalSide.SELL),
            _batch(strategy="mean_reversion", side=SignalSide.BUY),
        ),
    )

    recommendation = report.get("TCS")

    assert recommendation.action is SignalSide.SELL
    assert recommendation.supporting_strategies == (
        "breakout",
        "momentum",
    )
    assert recommendation.opposing_strategies == ("mean_reversion",)


def test_ensemble_decision_engine_builds_hold_on_tie() -> None:
    report = EnsembleDecisionEngine().decide(
        ranking=_ranking(),
        batches=(
            _batch(strategy="momentum", side=SignalSide.BUY),
            _batch(strategy="breakout", side=SignalSide.SELL),
        ),
    )

    recommendation = report.get("TCS")

    assert recommendation.action is SignalSide.HOLD
    assert recommendation.is_actionable is False
    assert recommendation.confidence == Decimal("0")
    assert recommendation.recommendation_score == Decimal("0")


def test_ensemble_decision_report_groups_actions() -> None:
    report = EnsembleDecisionReport(
        generated_for=date(2026, 1, 10),
        recommendations=(
            _recommendation(symbol="TCS", action=SignalSide.BUY),
            _recommendation(symbol="INFY", action=SignalSide.SELL),
            _recommendation(symbol="RELIANCE", action=SignalSide.HOLD),
        ),
    )

    assert report.recommendation_count == 3
    assert tuple(row.symbol for row in report.actionable) == (
        "TCS",
        "INFY",
    )
    assert tuple(row.symbol for row in report.buys) == ("TCS",)
    assert tuple(row.symbol for row in report.sells) == ("INFY",)
    assert tuple(row.symbol for row in report.holds) == ("RELIANCE",)


def test_ensemble_decision_engine_rejects_duplicate_strategy_symbol() -> None:
    with pytest.raises(ValueError, match="duplicate strategy signal"):
        EnsembleDecisionEngine().decide(
            ranking=_ranking(),
            batches=(
                SignalBatch(
                    strategy="momentum",
                    generated_for=date(2026, 1, 10),
                    signals=(
                        _signal(strategy="momentum", side=SignalSide.BUY),
                        _signal(strategy="momentum", side=SignalSide.SELL),
                    ),
                ),
            ),
        )


def test_ensemble_decision_engine_rejects_mixed_dates() -> None:
    with pytest.raises(ValueError, match="share the same generated date"):
        EnsembleDecisionEngine().decide(
            ranking=_ranking(),
            batches=(
                _batch(strategy="momentum", side=SignalSide.BUY),
                SignalBatch(
                    strategy="breakout",
                    generated_for=date(2026, 1, 11),
                    signals=(
                        TradingSignal(
                            symbol="TCS",
                            side=SignalSide.BUY,
                            strategy="breakout",
                            generated_for=date(2026, 1, 11),
                        ),
                    ),
                ),
            ),
        )


def test_trade_recommendation_validates_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        TradeRecommendation(
            symbol="TCS",
            action=SignalSide.BUY,
            confidence=Decimal("1.1"),
            score=Decimal("1"),
            supporting_strategies=("momentum",),
            opposing_strategies=(),
            neutral_strategies=(),
            reasons=("too high",),
        )


def _ranking() -> StrategyRankingReport:
    return StrategyRankingReport(
        ranked=(
            _ranked_strategy(
                rank=1,
                strategy="momentum",
                score=Decimal("0.5"),
            ),
            _ranked_strategy(
                rank=2,
                strategy="breakout",
                score=Decimal("0.5"),
            ),
            _ranked_strategy(
                rank=3,
                strategy="mean_reversion",
                score=Decimal("0.5"),
            ),
        )
    )


def _ranked_strategy(
    *,
    rank: int,
    strategy: str,
    score: Decimal,
) -> RankedStrategy:
    return RankedStrategy(
        rank=rank,
        strategy=strategy,
        robustness_score=score,
        hit_rate=Decimal("1"),
        average_score=score,
        coverage=Decimal("1"),
        composite_score=score,
        fold_count=1,
        evaluated_signals=1,
        actionable_signals=1,
        winning_signals=1,
    )


def _batch(
    *,
    strategy: str,
    side: SignalSide,
) -> SignalBatch:
    return SignalBatch(
        strategy=strategy,
        generated_for=date(2026, 1, 10),
        signals=(_signal(strategy=strategy, side=side),),
    )


def _signal(
    *,
    strategy: str,
    side: SignalSide,
) -> TradingSignal:
    return TradingSignal(
        symbol="TCS",
        side=side,
        strategy=strategy,
        generated_for=date(2026, 1, 10),
    )


def _recommendation(
    *,
    symbol: str,
    action: SignalSide,
) -> TradeRecommendation:
    return TradeRecommendation(
        symbol=symbol,
        action=action,
        confidence=Decimal("1"),
        score=Decimal("1"),
        supporting_strategies=("momentum",),
        opposing_strategies=(),
        neutral_strategies=(),
        reasons=("test recommendation",),
        agreement_score=Decimal("1"),
        strategy_quality_score=Decimal("1"),
        signal_confidence_score=Decimal("1"),
        coverage_score=Decimal("1"),
        recommendation_score=Decimal("1"),
    )
