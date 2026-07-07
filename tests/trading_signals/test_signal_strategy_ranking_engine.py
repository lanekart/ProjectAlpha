from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import SignalBatch, SignalSide, TradingSignal
from alpha.trading_signals.ranking import (
    RankedStrategy,
    StrategyRankingEngine,
    StrategyRankingReport,
)
from alpha.trading_signals.research import MultiStrategyResearchEngine
from alpha.trading_signals.walk_forward import (
    SignalOutcome,
    WalkForwardConfig,
    WalkForwardPlanner,
)


def test_strategy_ranking_engine_orders_research_results() -> None:
    report = _research_report()

    ranking = StrategyRankingEngine().rank(report)

    assert ranking.strategy_count == 3
    assert ranking.strategies == (
        "breakout",
        "momentum",
        "mean_reversion",
    )
    assert ranking.best is not None
    assert ranking.best.strategy == "breakout"
    assert ranking.best.rank == 1
    assert ranking.get("momentum").rank == 2


def test_ranked_strategy_exposes_actionable_status() -> None:
    report = _research_report()

    ranking = StrategyRankingEngine().rank(report)

    assert ranking.get("breakout").is_actionable is True
    assert ranking.get("mean_reversion").is_actionable is False


def test_strategy_ranking_report_is_deterministic() -> None:
    report = _research_report()
    engine = StrategyRankingEngine()

    first = engine.rank(report)
    second = engine.rank(report)

    assert first == second
    assert tuple(row.rank for row in first.ranked) == (1, 2, 3)


def test_strategy_ranking_report_rejects_duplicate_strategies() -> None:
    row = _ranked_strategy(rank=1, strategy="momentum")

    with pytest.raises(ValueError, match="duplicate ranked strategy"):
        StrategyRankingReport(
            ranked=(
                row,
                _ranked_strategy(rank=2, strategy="momentum"),
            )
        )


def test_strategy_ranking_report_rejects_non_contiguous_ranks() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        StrategyRankingReport(
            ranked=(
                _ranked_strategy(rank=1, strategy="momentum"),
                _ranked_strategy(rank=3, strategy="breakout"),
            )
        )


def test_ranked_strategy_validates_signal_counts() -> None:
    with pytest.raises(ValueError, match="winning signals"):
        RankedStrategy(
            rank=1,
            strategy="momentum",
            robustness_score=Decimal("0"),
            hit_rate=Decimal("0"),
            average_score=Decimal("0"),
            coverage=Decimal("0"),
            composite_score=Decimal("0"),
            fold_count=1,
            evaluated_signals=1,
            actionable_signals=1,
            winning_signals=2,
        )


def _research_report():
    windows = WalkForwardPlanner().plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 5),
            train_days=3,
            test_days=2,
            step_days=1,
        )
    )
    return MultiStrategyResearchEngine().run(
        strategies=(
            "momentum",
            "breakout",
            "mean_reversion",
        ),
        windows=windows,
        batches_by_strategy={
            "momentum": (
                _batch(
                    strategy="momentum",
                    generated_for=date(2026, 1, 4),
                    symbol="TCS",
                    side=SignalSide.BUY,
                ),
            ),
            "breakout": (
                _batch(
                    strategy="breakout",
                    generated_for=date(2026, 1, 4),
                    symbol="INFY",
                    side=SignalSide.BUY,
                ),
            ),
            "mean_reversion": (
                _batch(
                    strategy="mean_reversion",
                    generated_for=date(2026, 1, 4),
                    symbol="RELIANCE",
                    side=SignalSide.HOLD,
                ),
            ),
        },
        outcomes=(
            SignalOutcome(
                symbol="TCS",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.03"),
            ),
            SignalOutcome(
                symbol="INFY",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.07"),
            ),
            SignalOutcome(
                symbol="RELIANCE",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.01"),
            ),
        ),
    )


def _ranked_strategy(
    *,
    rank: int,
    strategy: str,
) -> RankedStrategy:
    return RankedStrategy(
        rank=rank,
        strategy=strategy,
        robustness_score=Decimal("0.1"),
        hit_rate=Decimal("1"),
        average_score=Decimal("0.1"),
        coverage=Decimal("1"),
        composite_score=Decimal("0.415"),
        fold_count=1,
        evaluated_signals=1,
        actionable_signals=1,
        winning_signals=1,
    )


def _batch(
    *,
    strategy: str,
    generated_for: date,
    symbol: str,
    side: SignalSide,
) -> SignalBatch:
    return SignalBatch(
        strategy=strategy,
        generated_for=generated_for,
        signals=(
            TradingSignal(
                symbol=symbol,
                side=side,
                strategy=strategy,
                generated_for=generated_for,
            ),
        ),
    )
