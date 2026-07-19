from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.benchmark_replay.metrics import portfolio_statistics
from alpha.benchmark_replay.models import CapitalCurveRecord, TradeRecord


def _curve(
    observed_on: date, value: str, daily: str, drawdown: str
) -> CapitalCurveRecord:
    return CapitalCurveRecord(
        observed_on=observed_on,
        cash=Decimal(value),
        invested_capital=Decimal("0"),
        portfolio_value=Decimal(value),
        idle_cash=Decimal(value),
        capital_utilisation_percent=Decimal("0"),
        daily_return_percent=Decimal(daily),
        drawdown_percent=Decimal(drawdown),
        open_positions=0,
        pending_orders=0,
    )


def _trade(identifier: str, net: str, return_percent: str) -> TradeRecord:
    return TradeRecord(
        trade_id=identifier,
        symbol=identifier,
        sector="UNKNOWN",
        decision_date=date(2024, 1, 1),
        entry_date=date(2024, 1, 2),
        exit_date=date(2024, 1, 5),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        initial_stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=None,
        target_3=None,
        quantity=Decimal("10"),
        gross_profit_loss=Decimal(net),
        net_profit_loss=Decimal(net),
        gross_return_percent=Decimal(return_percent),
        net_return_percent=Decimal(return_percent),
        realised_r=Decimal("1"),
        holding_sessions=3,
        holding_days=3,
        exit_reason="TARGET_1" if Decimal(net) > 0 else "STOP",
        targets_hit=(1,) if Decimal(net) > 0 else (),
        transaction_cost=Decimal("0"),
        slippage_cost=Decimal("0"),
        ambiguity_count=0,
    )


def test_zero_trade_metrics_remain_unavailable_not_fabricated() -> None:
    stats = portfolio_statistics(
        starting_capital=Decimal("1000"),
        capital_curve=(
            _curve(date(2024, 1, 1), "1000", "0", "0"),
            _curve(date(2025, 1, 1), "1000", "0", "0"),
        ),
        trades=(),
        turnover=Decimal("0"),
    )
    assert stats.win_rate_percent is None
    assert stats.profit_factor is None
    assert stats.expectancy_percent is None
    assert stats.sharpe_ratio is None
    assert stats.cagr_percent == Decimal("0.00")


def test_trade_and_drawdown_metrics_are_deterministic() -> None:
    stats = portfolio_statistics(
        starting_capital=Decimal("1000"),
        capital_curve=(
            _curve(date(2024, 1, 1), "1000", "0", "0"),
            _curve(date(2024, 1, 2), "1100", "10", "0"),
            _curve(date(2024, 1, 3), "990", "-10", "-10"),
        ),
        trades=(_trade("WIN", "100", "10"), _trade("LOSS", "-50", "-5")),
        turnover=Decimal("2000"),
    )
    assert stats.win_rate_percent == Decimal("50.00")
    assert stats.profit_factor == Decimal("2.0000")
    assert stats.expectancy_percent == Decimal("2.5000")
    assert stats.maximum_drawdown_percent == Decimal("10.00")
    assert stats.turnover_percent == Decimal("200.00")
