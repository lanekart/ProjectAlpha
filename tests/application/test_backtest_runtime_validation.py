from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from alpha.application.backtest import BacktestApplicationService


def test_backtest_runtime_preserves_dated_mark_to_market_equity_curve() -> None:
    frames = {
        date(2026, 1, 1): pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "close": [Decimal("100")],
                "signal": ["BUY"],
            }
        ),
        date(2026, 1, 2): pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "close": [Decimal("120")],
                "signal": ["HOLD"],
            }
        ),
        date(2026, 1, 3): pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "close": [Decimal("80")],
                "signal": ["HOLD"],
            }
        ),
    }

    class Resolver:
        def resolve(self, requested_date: date) -> date:
            return requested_date

    class Downloader:
        def download(self, trading_day: date) -> Path:
            return Path(f"{trading_day.isoformat()}.zip")

    class Ingestion:
        def ingest(self, archive: Path) -> pd.DataFrame:
            trade_date = date.fromisoformat(archive.stem)
            return frames[trade_date]

        def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
            return frames[trade_date]

    class Report:
        def generate(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
            return {"signals": df}

    service = BacktestApplicationService(
        resolver=Resolver(),  # type: ignore[arg-type]
        downloader=Downloader(),  # type: ignore[arg-type]
        ingestion=Ingestion(),  # type: ignore[arg-type]
        report=Report(),
    )

    run = service.run(
        strategy="momentum",
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        starting_cash=Decimal("1000"),
    )

    curve = run.summary.result.equity_curve

    assert run.summary.processed_days == 3
    assert run.summary.order_count == 1
    assert run.summary.trade_count == 1
    assert run.summary.position_count == 1
    assert run.summary.positions == {"AAPL": 1}

    assert len(curve) == 3
    assert [point.timestamp for point in curve] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [point.cash for point in curve] == [
        Decimal("900"),
        Decimal("900"),
        Decimal("900"),
    ]
    assert [point.holdings_market_value for point in curve] == [
        Decimal("100"),
        Decimal("120"),
        Decimal("80"),
    ]
    assert [point.equity for point in curve] == [
        Decimal("1000"),
        Decimal("1020"),
        Decimal("980"),
    ]

    assert run.summary.ending_cash == Decimal("900")
    assert run.summary.equity == Decimal("980")
    assert run.summary.performance.total_return == Decimal("-0.02")
    assert run.summary.performance.volatility > Decimal("0")
    assert run.summary.maximum_drawdown < Decimal("0")
