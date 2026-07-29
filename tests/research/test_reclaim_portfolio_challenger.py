from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from alpha.research.reclaim_portfolio_challenger import (
    ChallengerConfig,
    engineer_signals,
    risk_sized_quantity,
    simulate_challenger,
)


def _market_frame(*, regime: str = "POSITIVE") -> pd.DataFrame:
    start = date(2020, 1, 1)
    rows: list[dict[str, object]] = []
    closes = [100 + index * 0.1 for index in range(230)]
    closes[-2] = 120.0
    closes[-1] = 125.0
    for index, close in enumerate(closes):
        rows.append(
            {
                "trading_date": start + timedelta(days=index),
                "security_id": "INE000000001",
                "symbol": "TEST",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 200.0 if index == len(closes) - 1 else 100.0,
                "final_signal": "BUY" if index == len(closes) - 1 else None,
                "regime": regime if index == len(closes) - 1 else None,
                "recommendation_score": 80.0 if index == len(closes) - 1 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _simulation_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults = {
        "security_id": "INE000000001",
        "symbol": "TEST",
        "sma20_previous": 100.0,
        "research_signal": False,
        "final_signal": None,
        "recommendation_score": 0.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _unconstrained_config(**changes: object) -> ChallengerConfig:
    return replace(
        ChallengerConfig(),
        initial_capital=Decimal("100000"),
        drawdown_throttle_percent=Decimal("90"),
        hard_stop_percent=Decimal("99"),
        **changes,
    )


def test_exact_reclaim_signal_is_generated() -> None:
    featured = engineer_signals(_market_frame(), ChallengerConfig())
    last = featured.iloc[-1]

    assert bool(last["alpha_signal_ok"])
    assert bool(last["positive_regime_ok"])
    assert bool(last["long_term_trend_ok"])
    assert bool(last["rising_sma20_ok"])
    assert bool(last["reclaim_ok"])
    assert bool(last["momentum_ok"])
    assert bool(last["volume_contraction_ok"])
    assert bool(last["volume_expansion_ok"])
    assert bool(last["research_signal"])


def test_non_positive_regime_rejects_the_same_reclaim() -> None:
    featured = engineer_signals(_market_frame(regime="NEUTRAL"), ChallengerConfig())

    assert not bool(featured.iloc[-1]["research_signal"])


def test_risk_sizing_uses_full_and_throttled_fraction() -> None:
    full = risk_sized_quantity(
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        risk_fraction=Decimal("0.01"),
    )
    throttled = risk_sized_quantity(
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        risk_fraction=Decimal("0.005"),
    )

    assert full == 200
    assert throttled == 100


def test_staged_exit_takes_half_at_2r_and_remainder_at_3r() -> None:
    frame = _simulation_frame(
        [
            {
                "trading_date": date(2024, 1, 1),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "research_signal": True,
                "final_signal": "BUY",
                "recommendation_score": 80,
            },
            {
                "trading_date": date(2024, 1, 2),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
            },
            {
                "trading_date": date(2024, 1, 3),
                "open": 100,
                "high": 116,
                "low": 99,
                "close": 115,
            },
        ]
    )

    result = simulate_challenger(frame, _unconstrained_config())
    trade = result.trades[0]

    assert trade.partial_exit_completed is True
    assert tuple(leg.reason for leg in trade.exit_legs) == (
        "TARGET_2R_PARTIAL",
        "TARGET_3R",
    )
    assert trade.gross_return_percent == Decimal("12.5000")


def test_remainder_trails_prior_session_sma20_after_partial_exit() -> None:
    frame = _simulation_frame(
        [
            {
                "trading_date": date(2024, 1, 1),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "research_signal": True,
                "final_signal": "STRONG_BUY",
                "recommendation_score": 90,
            },
            {
                "trading_date": date(2024, 1, 2),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
            },
            {
                "trading_date": date(2024, 1, 3),
                "open": 100,
                "high": 111,
                "low": 99,
                "close": 110,
                "sma20_previous": 100,
            },
            {
                "trading_date": date(2024, 1, 4),
                "open": 106,
                "high": 110,
                "low": 104,
                "close": 105,
                "sma20_previous": 105,
            },
        ]
    )

    result = simulate_challenger(frame, _unconstrained_config())
    trade = result.trades[0]

    assert trade.final_exit_reason == "TRAIL_20DMA"
    assert trade.exit_legs[-1].exit_price == Decimal("105")
    assert trade.gross_return_percent == Decimal("7.5000")


def test_same_session_stop_and_target_is_resolved_stop_first() -> None:
    frame = _simulation_frame(
        [
            {
                "trading_date": date(2024, 1, 1),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "research_signal": True,
                "final_signal": "BUY",
                "recommendation_score": 80,
            },
            {
                "trading_date": date(2024, 1, 2),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
            },
            {
                "trading_date": date(2024, 1, 3),
                "open": 100,
                "high": 116,
                "low": 94,
                "close": 110,
            },
        ]
    )

    result = simulate_challenger(frame, _unconstrained_config())
    trade = result.trades[0]

    assert trade.final_exit_reason == "INTRADAY_PATH_AMBIGUOUS_STOP_FIRST"
    assert trade.partial_exit_completed is False
    assert trade.gross_return_percent == Decimal("-5.0000")
    assert result.ambiguous_session_count == 1


def test_portfolio_hard_stop_liquidates_and_terminates() -> None:
    config = replace(
        ChallengerConfig(),
        initial_capital=Decimal("10000"),
        full_risk_fraction=Decimal("0.5"),
        throttled_risk_fraction=Decimal("0.25"),
        maximum_positions=1,
    )
    frame = _simulation_frame(
        [
            {
                "trading_date": date(2024, 1, 1),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "research_signal": True,
                "final_signal": "BUY",
                "recommendation_score": 80,
            },
            {
                "trading_date": date(2024, 1, 2),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
            },
            {
                "trading_date": date(2024, 1, 3),
                "open": 80,
                "high": 80,
                "low": 80,
                "close": 80,
            },
            {
                "trading_date": date(2024, 1, 4),
                "open": 80,
                "high": 81,
                "low": 79,
                "close": 80,
                "research_signal": True,
                "final_signal": "BUY",
                "recommendation_score": 80,
            },
        ]
    )

    result = simulate_challenger(frame, config)

    assert result.hard_stop_date == date(2024, 1, 3)
    assert result.ending_equity == Decimal("8000")
    assert result.entry_count == 1
    assert result.equity_curve[-1].hard_stop_active is True
