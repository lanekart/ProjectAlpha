from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from alpha.application.backtest import CliBacktestService
from alpha.backtest.engine import BacktestEngine


@dataclass(slots=True)
class FakeResolver:
    def resolve(self, requested_date: date) -> date:
        return requested_date


@dataclass(slots=True)
class FakeDownloader:
    def download(self, trading_day: date) -> Path:
        return Path(f"/tmp/{trading_day.isoformat()}.zip")


@dataclass(slots=True)
class FakeIngestion:
    frame: pd.DataFrame

    def ingest(self, zip_path: Path) -> pd.DataFrame:
        return self.frame


@dataclass(slots=True)
class FakeReport:
    signal_frame: pd.DataFrame

    def generate(self, df: pd.DataFrame) -> dict[str, Any]:
        return {"signals": self.signal_frame}


def test_cli_backtest_service_runs_engine_for_momentum_strategy() -> None:
    market_frame = pd.DataFrame(
        [
            {"symbol": "RELIANCE", "close": 2500},
            {"symbol": "TCS", "close": 4000},
        ]
    )
    signal_frame = pd.DataFrame(
        [
            {"symbol": "RELIANCE", "signal": "BUY"},
            {"symbol": "TCS", "signal": "HOLD"},
        ]
    )

    service = CliBacktestService(
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(market_frame),
        report=FakeReport(signal_frame),
        engine=BacktestEngine(),
    )

    summary = service.run(
        strategy="momentum",
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
        starting_cash=Decimal("100000"),
    )

    assert summary.strategy == "momentum"
    assert summary.processed_days == 1
    assert summary.order_count == 1
    assert summary.result.trade_count == 1
    assert summary.result.positions == {"RELIANCE": 1}
    assert summary.result.ending_cash == Decimal("97500")
    assert summary.result.equity == Decimal("100000")


def test_cli_backtest_service_rejects_unsupported_strategy() -> None:
    service = CliBacktestService(
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(pd.DataFrame()),
        report=FakeReport(pd.DataFrame()),
        engine=BacktestEngine(),
    )

    with pytest.raises(ValueError, match="unsupported backtest strategy"):
        service.run(
            strategy="mean_reversion",
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
            starting_cash=Decimal("100000"),
        )
