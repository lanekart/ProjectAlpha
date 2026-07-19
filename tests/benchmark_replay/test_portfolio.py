from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.benchmark_replay.models import BenchmarkPolicy
from alpha.benchmark_replay.portfolio import (
    ExecutionCandidate,
    MarketBar,
    PortfolioReplayEngine,
)


def _candidate(symbol: str = "ALPHA") -> ExecutionCandidate:
    return ExecutionCandidate(
        symbol=symbol,
        sector="UNKNOWN",
        decision_date=date(2024, 1, 1),
        opportunity_score=Decimal("90"),
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("105"),
        confirmation_entry=Decimal("105"),
        maximum_chase_price=Decimal("110"),
        stop=Decimal("90"),
        target_1=Decimal("120"),
        target_2=Decimal("130"),
        target_3=Decimal("140"),
        atr=Decimal("5"),
        maximum_holding_sessions=10,
    )


def test_next_session_entry_partial_target_and_runner_exit() -> None:
    engine = PortfolioReplayEngine(BenchmarkPolicy(initial_capital=Decimal("100000")))
    assert engine.submit(_candidate()) is None

    engine.advance(
        date(2024, 1, 2),
        {
            "ALPHA": MarketBar(
                Decimal("102"), Decimal("108"), Decimal("99"), Decimal("106")
            )
        },
    )
    assert engine.position_count == 1
    assert engine.entered_today == 1

    engine.advance(
        date(2024, 1, 3),
        {
            "ALPHA": MarketBar(
                Decimal("110"), Decimal("121"), Decimal("105"), Decimal("118")
            )
        },
    )
    assert engine.position_count == 1
    engine.advance(
        date(2024, 1, 4),
        {
            "ALPHA": MarketBar(
                Decimal("123"), Decimal("132"), Decimal("122"), Decimal("131")
            )
        },
    )

    assert engine.position_count == 0
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "TARGET_2"
    assert engine.trades[0].targets_hit == (1, 2)
    assert engine.trades[0].net_profit_loss > 0


def test_stop_precedes_target_when_both_touch_same_bar() -> None:
    engine = PortfolioReplayEngine(BenchmarkPolicy(initial_capital=Decimal("100000")))
    engine.submit(_candidate())
    engine.advance(
        date(2024, 1, 2),
        {
            "ALPHA": MarketBar(
                Decimal("102"), Decimal("108"), Decimal("99"), Decimal("106")
            )
        },
    )
    engine.advance(
        date(2024, 1, 3),
        {
            "ALPHA": MarketBar(
                Decimal("95"), Decimal("125"), Decimal("85"), Decimal("100")
            )
        },
    )

    trade = engine.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.ambiguity_count == 1
    assert trade.exit_price < trade.entry_price


def test_position_limit_and_cash_reserve_are_fail_closed() -> None:
    policy = BenchmarkPolicy(
        initial_capital=Decimal("100000"),
        maximum_positions=1,
    )
    engine = PortfolioReplayEngine(policy)
    assert engine.submit(_candidate("ONE")) is None
    assert engine.submit(_candidate("TWO")) == "RANKING_POSITION_LIMIT"
    engine.advance(
        date(2024, 1, 2),
        {
            "ONE": MarketBar(
                Decimal("102"), Decimal("108"), Decimal("99"), Decimal("106")
            )
        },
    )
    assert engine.cash >= Decimal("70000")
    assert engine.capital_curve[-1].capital_utilisation_percent <= Decimal("10.50")
