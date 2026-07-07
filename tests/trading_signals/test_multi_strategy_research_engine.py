from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.trading_signals import SignalBatch, SignalSide, TradingSignal
from alpha.trading_signals.research import (
    MultiStrategyResearchEngine,
    MultiStrategyResearchReport,
    StrategyResearchResult,
)
from alpha.trading_signals.walk_forward import (
    SignalOutcome,
    WalkForwardConfig,
    WalkForwardPlanner,
    WalkForwardValidator,
)


def test_multi_strategy_research_engine_runs_each_strategy() -> None:
    windows = WalkForwardPlanner().plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 5),
            train_days=3,
            test_days=2,
            step_days=1,
        )
    )

    report = MultiStrategyResearchEngine().run(
        strategies=("momentum", "breakout"),
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
                    side=SignalSide.SELL,
                ),
            ),
        },
        outcomes=(
            SignalOutcome(
                symbol="TCS",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.05"),
            ),
            SignalOutcome(
                symbol="INFY",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("-0.02"),
            ),
        ),
    )

    assert report.strategy_count == 2
    assert report.strategies == ("breakout", "momentum")
    assert report.evaluated_signals == 2
    assert report.actionable_signals == 2
    assert report.winning_signals == 2
    assert report.hit_rate == Decimal("1")
    assert report.get("momentum").average_score == Decimal("0.05")
    assert report.get("breakout").average_score == Decimal("0.02")


def test_multi_strategy_research_report_ranks_by_robustness() -> None:
    windows = WalkForwardPlanner().plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 5),
            train_days=3,
            test_days=2,
            step_days=1,
        )
    )

    report = MultiStrategyResearchEngine().run(
        strategies=("slow", "fast"),
        windows=windows,
        batches_by_strategy={
            "slow": (
                _batch(
                    strategy="slow",
                    generated_for=date(2026, 1, 4),
                    symbol="TCS",
                    side=SignalSide.BUY,
                ),
            ),
            "fast": (
                _batch(
                    strategy="fast",
                    generated_for=date(2026, 1, 4),
                    symbol="INFY",
                    side=SignalSide.BUY,
                ),
            ),
        },
        outcomes=(
            SignalOutcome(
                symbol="TCS",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.01"),
            ),
            SignalOutcome(
                symbol="INFY",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.08"),
            ),
        ),
    )

    assert tuple(result.strategy for result in report.ranked_results) == (
        "fast",
        "slow",
    )
    assert report.best_result is not None
    assert report.best_result.strategy == "fast"


def test_strategy_research_result_requires_matching_validation() -> None:
    validation = WalkForwardValidator().validate(
        strategy="momentum",
        windows=(),
        batches=(),
        outcomes=(),
    )

    with pytest.raises(ValueError, match="validation strategy"):
        StrategyResearchResult(
            strategy="breakout",
            validation=validation,
        )


def test_multi_strategy_research_report_rejects_duplicates() -> None:
    validation = WalkForwardValidator().validate(
        strategy="momentum",
        windows=(),
        batches=(),
        outcomes=(),
    )
    result = StrategyResearchResult(
        strategy="momentum",
        validation=validation,
    )

    with pytest.raises(ValueError, match="duplicate strategy"):
        MultiStrategyResearchReport(
            results=(result, result),
        )


def test_multi_strategy_research_engine_validates_batch_mapping() -> None:
    with pytest.raises(ValueError, match="batch strategy"):
        MultiStrategyResearchEngine().run(
            strategies=("momentum",),
            windows=(),
            batches_by_strategy={
                "momentum": (
                    _batch(
                        strategy="breakout",
                        generated_for=date(2026, 1, 4),
                        symbol="TCS",
                        side=SignalSide.BUY,
                    ),
                ),
            },
            outcomes=(),
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
