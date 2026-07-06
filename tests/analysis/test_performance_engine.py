from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alpha.analysis.performance.engine import PerformanceEngine
from alpha.portfolio.equity_curve import EquityCurve, EquityPoint


def make_point(day: int, equity: Decimal) -> EquityPoint:
    return EquityPoint(
        timestamp=datetime.now(UTC) + timedelta(days=day),
        equity=equity,
        cash=Decimal("0"),
        market_value=equity,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
    )


def test_performance_engine_generates_report() -> None:
    curve = EquityCurve(
        (
            make_point(0, Decimal("100")),
            make_point(1, Decimal("110")),
            make_point(2, Decimal("105")),
        )
    )

    report = PerformanceEngine().analyze(curve)

    assert report.total_return == Decimal("0.05")
    assert report.max_drawdown == Decimal("105") / Decimal("110") - Decimal("1")
    assert report.observations == 3
    assert report.best_return == Decimal("0.1")
    assert report.worst_return == Decimal("105") / Decimal("110") - Decimal("1")


def test_performance_engine_handles_flat_curve() -> None:
    curve = EquityCurve(
        (
            make_point(0, Decimal("100")),
            make_point(1, Decimal("100")),
        )
    )

    report = PerformanceEngine().analyze(curve)

    assert report.total_return == Decimal("0")
    assert report.volatility == Decimal("0")
    assert report.sharpe == Decimal("0")
    assert report.sortino == Decimal("0")
    assert report.calmar == Decimal("0")
