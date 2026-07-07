from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.backtest import BacktestResult, EquityCurvePoint, PerformanceAnalytics


def make_point(
    timestamp: date,
    equity: Decimal,
    daily_return: Decimal = Decimal("0"),
    drawdown: Decimal = Decimal("0"),
    cumulative_return: Decimal = Decimal("0"),
) -> EquityCurvePoint:
    return EquityCurvePoint(
        timestamp=timestamp,
        cash=equity,
        holdings_market_value=Decimal("0"),
        equity=equity,
        daily_return=daily_return,
        drawdown=drawdown,
        cumulative_return=cumulative_return,
    )


def test_performance_analytics_uses_result_equity_curve_by_default() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("120"),
        equity=Decimal("120"),
        positions={},
        trades=(),
        equity_curve=(
            make_point(date(2026, 1, 1), Decimal("120")),
            make_point(date(2026, 1, 2), Decimal("90")),
            make_point(date(2026, 1, 3), Decimal("130")),
            make_point(date(2026, 1, 4), Decimal("120")),
        ),
    )

    summary = PerformanceAnalytics(periods_per_year=Decimal("4")).summarize(result)

    assert summary.total_return == Decimal("0.20")
    assert summary.maximum_drawdown == Decimal("-0.25")
    assert summary.volatility > Decimal("0")
    assert summary.sharpe_ratio != Decimal("0")
    assert summary.sortino_ratio != Decimal("0")
    assert summary.calmar_ratio != Decimal("0")


def test_explicit_equity_curve_overrides_embedded_result_curve() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("120"),
        equity=Decimal("120"),
        positions={},
        trades=(),
        equity_curve=(
            make_point(date(2026, 1, 1), Decimal("80")),
            make_point(date(2026, 1, 2), Decimal("120")),
        ),
    )

    summary = PerformanceAnalytics(periods_per_year=Decimal("4")).summarize(
        result,
        equity_curve=(
            Decimal("100"),
            Decimal("120"),
            Decimal("90"),
            Decimal("130"),
            Decimal("120"),
        ),
    )

    assert summary.maximum_drawdown == Decimal("-0.25")


def test_legacy_result_without_equity_curve_keeps_two_point_fallback() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100"),
        ending_cash=Decimal("120"),
        equity=Decimal("120"),
        positions={},
        trades=(),
    )

    summary = PerformanceAnalytics(periods_per_year=Decimal("4")).summarize(result)

    assert summary.total_return == Decimal("0.20")
    assert summary.maximum_drawdown == Decimal("0")
    assert summary.volatility == Decimal("0")
