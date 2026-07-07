from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.trading_signals import SignalBatch, SignalSide, TradingSignal
from alpha.trading_signals.walk_forward import (
    SignalOutcome,
    WalkForwardConfig,
    WalkForwardMode,
    WalkForwardPlanner,
    WalkForwardValidator,
)


def test_walk_forward_planner_creates_rolling_windows() -> None:
    planner = WalkForwardPlanner()

    windows = planner.plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 10),
            train_days=3,
            test_days=2,
            step_days=2,
        )
    )

    assert tuple(window.index for window in windows) == (1, 2, 3)
    assert windows[0].train_start == date(2026, 1, 1)
    assert windows[0].train_end == date(2026, 1, 3)
    assert windows[0].test_start == date(2026, 1, 4)
    assert windows[0].test_end == date(2026, 1, 5)
    assert windows[2].train_start == date(2026, 1, 5)
    assert windows[2].test_end == date(2026, 1, 9)


def test_walk_forward_planner_creates_expanding_windows() -> None:
    planner = WalkForwardPlanner()

    windows = planner.plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 8),
            train_days=3,
            test_days=1,
            step_days=2,
            mode=WalkForwardMode.EXPANDING,
        )
    )

    assert tuple(window.train_start for window in windows) == (
        date(2026, 1, 1),
        date(2026, 1, 1),
        date(2026, 1, 1),
    )
    assert tuple(window.train_end for window in windows) == (
        date(2026, 1, 3),
        date(2026, 1, 5),
        date(2026, 1, 7),
    )


def test_walk_forward_validator_scores_actionable_signals() -> None:
    planner = WalkForwardPlanner()
    windows = planner.plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 5),
            train_days=3,
            test_days=2,
            step_days=1,
        )
    )
    batch = SignalBatch(
        strategy="momentum",
        generated_for=date(2026, 1, 4),
        signals=(
            TradingSignal(
                symbol="TCS",
                side=SignalSide.BUY,
                strategy="momentum",
                generated_for=date(2026, 1, 4),
            ),
            TradingSignal(
                symbol="INFY",
                side=SignalSide.SELL,
                strategy="momentum",
                generated_for=date(2026, 1, 4),
            ),
            TradingSignal(
                symbol="HDFC",
                side=SignalSide.HOLD,
                strategy="momentum",
                generated_for=date(2026, 1, 4),
            ),
        ),
    )

    report = WalkForwardValidator().validate(
        strategy="momentum",
        windows=windows,
        batches=(batch,),
        outcomes=(
            SignalOutcome(
                symbol="TCS",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.03"),
            ),
            SignalOutcome(
                symbol="INFY",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("-0.02"),
            ),
            SignalOutcome(
                symbol="HDFC",
                observed_for=date(2026, 1, 4),
                forward_return=Decimal("0.01"),
            ),
        ),
    )

    assert report.fold_count == 1
    assert report.evaluated_signals == 3
    assert report.actionable_signals == 2
    assert report.winning_signals == 2
    assert report.hit_rate == Decimal("1")
    assert report.average_score == Decimal("0.05") / Decimal("3")


def test_walk_forward_validator_filters_other_strategies() -> None:
    window = WalkForwardPlanner().plan(
        WalkForwardConfig(
            start=date(2026, 1, 1),
            end=date(2026, 1, 4),
            train_days=2,
            test_days=1,
            step_days=1,
        )
    )[0]
    batch = SignalBatch(
        strategy="other",
        generated_for=date(2026, 1, 3),
        signals=(
            TradingSignal(
                symbol="TCS",
                side=SignalSide.BUY,
                strategy="other",
                generated_for=date(2026, 1, 3),
            ),
        ),
    )

    report = WalkForwardValidator().validate(
        strategy="momentum",
        windows=(window,),
        batches=(batch,),
        outcomes=(
            SignalOutcome(
                symbol="TCS",
                observed_for=date(2026, 1, 3),
                forward_return=Decimal("0.10"),
            ),
        ),
    )

    assert report.evaluated_signals == 0
    assert report.hit_rate == Decimal("0")
    assert report.average_score == Decimal("0")
