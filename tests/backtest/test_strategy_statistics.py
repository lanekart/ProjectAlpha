from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from alpha.backtest import PerformanceSummary, StrategyStatisticsEngine


def make_performance_summary() -> PerformanceSummary:
    return PerformanceSummary(
        total_return=Decimal("0.50"),
        cagr=Decimal("0.25"),
        volatility=Decimal("0.15"),
        sharpe_ratio=Decimal("1.6"),
        sortino_ratio=Decimal("2.1"),
        calmar_ratio=Decimal("1.25"),
        maximum_drawdown=Decimal("-0.20"),
        win_rate=Decimal("0.60"),
        profit_factor=Decimal("2"),
        average_win=Decimal("200"),
        average_loss=Decimal("-100"),
        expectancy=Decimal("80"),
        exposure=Decimal("0.75"),
        ending_equity=Decimal("150000"),
        cash_balance=Decimal("25000"),
    )


def test_strategy_statistics_are_immutable() -> None:
    statistics = StrategyStatisticsEngine().summarize(make_performance_summary())

    with pytest.raises(FrozenInstanceError):
        statistics.recovery_factor = Decimal("0")  # type: ignore[misc]


def test_strategy_statistics_engine_computes_core_statistics() -> None:
    statistics = StrategyStatisticsEngine(
        periods_per_year=Decimal("252"),
    ).summarize(
        make_performance_summary(),
        trade_pnls=(
            Decimal("200"),
            Decimal("100"),
            Decimal("-50"),
            Decimal("-100"),
            Decimal("300"),
        ),
        observed_periods=Decimal("5").to_integral_exact(),
    )

    assert statistics.recovery_factor == Decimal("2.5")
    assert statistics.gain_to_pain_ratio == Decimal("4")
    assert statistics.payoff_ratio == Decimal("2")
    assert statistics.kelly_fraction == Decimal("0.40")
    assert statistics.risk_of_ruin == (Decimal("0.40") / Decimal("0.60")) ** Decimal(
        "10"
    )
    assert statistics.consecutive_wins == 2
    assert statistics.consecutive_losses == 2
    assert statistics.trade_frequency == Decimal("252")
    assert statistics.annual_return == Decimal("0.25")
    assert statistics.monthly_return > Decimal("0")


def test_strategy_statistics_engine_computes_sqn_for_trade_pnls() -> None:
    statistics = StrategyStatisticsEngine().summarize(
        make_performance_summary(),
        trade_pnls=(
            Decimal("100"),
            Decimal("200"),
            Decimal("-50"),
            Decimal("150"),
        ),
        observed_periods=4,
    )

    assert statistics.system_quality_number > Decimal("0")


def test_strategy_statistics_engine_returns_zero_for_missing_trade_series() -> None:
    statistics = StrategyStatisticsEngine().summarize(make_performance_summary())

    assert statistics.gain_to_pain_ratio == Decimal("0")
    assert statistics.system_quality_number == Decimal("0")
    assert statistics.consecutive_wins == 0
    assert statistics.consecutive_losses == 0
    assert statistics.trade_frequency == Decimal("0")


def test_strategy_statistics_engine_handles_no_drawdown() -> None:
    performance = PerformanceSummary(
        total_return=Decimal("0.50"),
        cagr=Decimal("0.25"),
        volatility=Decimal("0.15"),
        sharpe_ratio=Decimal("1.6"),
        sortino_ratio=Decimal("2.1"),
        calmar_ratio=Decimal("0"),
        maximum_drawdown=Decimal("0"),
        win_rate=Decimal("1"),
        profit_factor=Decimal("10"),
        average_win=Decimal("200"),
        average_loss=Decimal("0"),
        expectancy=Decimal("200"),
        exposure=Decimal("0.75"),
        ending_equity=Decimal("150000"),
        cash_balance=Decimal("25000"),
    )

    statistics = StrategyStatisticsEngine().summarize(performance)

    assert statistics.recovery_factor == Decimal("0")
    assert statistics.payoff_ratio == Decimal("0")
    assert statistics.kelly_fraction == Decimal("0")
    assert statistics.risk_of_ruin == Decimal("0")


def test_strategy_statistics_engine_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="periods_per_year must be greater than zero"):
        StrategyStatisticsEngine(periods_per_year=Decimal("0"))

    with pytest.raises(ValueError, match="months_per_year must be greater than zero"):
        StrategyStatisticsEngine(months_per_year=Decimal("0"))


def test_strategy_statistics_engine_rejects_negative_observed_periods() -> None:
    with pytest.raises(ValueError, match="observed_periods cannot be negative"):
        StrategyStatisticsEngine().summarize(
            make_performance_summary(),
            observed_periods=-1,
        )
