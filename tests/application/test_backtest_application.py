from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from alpha.application.backtest import BacktestApplicationService, BacktestSummary
from alpha.backtest.models import BacktestResult, BacktestTrade


def test_backtest_summary_exposes_stable_metrics() -> None:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("100"),
        equity=Decimal("1100"),
        positions={"AAPL": 10},
        trades=(),
    )

    summary = BacktestSummary(
        strategy=" Momentum ",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        equity=result.equity,
        processed_days=22,
        order_count=1,
        trade_count=result.trade_count,
        position_count=1,
        positions=result.positions,
        result=result,
    )

    report = summary.report.as_dict()

    assert summary.strategy == "momentum"
    assert summary.total_return == Decimal("0.1")
    assert summary.performance.total_return == Decimal("0.1")
    assert summary.performance_report.as_dict()["total_return"] == "0.1"
    assert summary.performance_report.as_dict()["ending_equity"] == "1100"
    assert summary.strategy_statistics.trade_frequency == Decimal("0")
    assert (
        summary.strategy_statistics_report.as_dict()["annual_return"]
        == (summary.performance_report.as_dict()["cagr"])
    )
    assert report["metadata"]["strategy"] == "momentum"
    assert report["performance"]["total_return"] == "0.1"
    assert summary.ending_equity == Decimal("1100")
    assert summary.cash_balance == Decimal("100")
    assert summary.exposure == Decimal("1000") / Decimal("1100")
    assert summary.position_count == 1
    assert summary.positions["AAPL"] == 10


def test_backtest_summary_derives_strategy_statistics_from_closed_trades() -> None:
    result = BacktestResult(
        starting_cash=Decimal("100000"),
        ending_cash=Decimal("100800"),
        equity=Decimal("100800"),
        positions={},
        trades=(
            BacktestTrade(
                symbol="ABC",
                quantity=10,
                price=Decimal("100"),
                notional=Decimal("1000"),
            ),
            BacktestTrade(
                symbol="ABC",
                quantity=-10,
                price=Decimal("120"),
                notional=Decimal("1200"),
            ),
            BacktestTrade(
                symbol="XYZ",
                quantity=10,
                price=Decimal("100"),
                notional=Decimal("1000"),
            ),
            BacktestTrade(
                symbol="XYZ",
                quantity=-10,
                price=Decimal("90"),
                notional=Decimal("900"),
            ),
        ),
    )

    summary = BacktestSummary(
        strategy="momentum",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        equity=result.equity,
        processed_days=22,
        order_count=4,
        trade_count=result.trade_count,
        position_count=0,
        positions=result.positions,
        result=result,
    )

    assert summary.strategy_statistics.consecutive_wins == 1
    assert summary.strategy_statistics.consecutive_losses == 1
    assert summary.strategy_statistics.trade_frequency == (
        Decimal("2") / Decimal("22") * Decimal("252")
    )
    assert summary.strategy_statistics_report.as_dict()["consecutive_wins"] == "1"


def test_backtest_reloads_persisted_prices_after_idempotent_ingestion() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "close": [Decimal("100")],
            "signal": ["BUY"],
        }
    )

    class Resolver:
        def resolve(self, requested_date: date) -> date:
            return requested_date

    class Downloader:
        def download(self, trading_day: date) -> Path:
            return Path(f"{trading_day.isoformat()}.zip")

    class Ingestion:
        def ingest(self, archive: Path) -> pd.DataFrame:
            return pd.DataFrame()

        def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
            return frame

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
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
        starting_cash=Decimal("1000"),
    )

    assert run.summary.order_count == 1
    assert run.summary.trade_count == 1
    assert run.summary.positions == {"AAPL": 1}


def test_backtest_summary_rejects_position_count_mismatch() -> None:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("1000"),
        equity=Decimal("1000"),
        positions={},
        trades=(),
    )

    with pytest.raises(ValueError, match="position count"):
        BacktestSummary(
            strategy="momentum",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            starting_cash=result.starting_cash,
            ending_cash=result.ending_cash,
            equity=result.equity,
            processed_days=22,
            order_count=0,
            trade_count=0,
            position_count=1,
            positions=result.positions,
            result=result,
        )
