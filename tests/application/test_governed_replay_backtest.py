"""Integration tests for the canonical-replay-backed backtest entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from alpha.application.governed_replay_backtest import (
    GovernedReplayBacktestService,
)
from alpha.backtest.engine import BacktestEngine
from alpha.recovery.corporate_actions import CorporateActionTimeline
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

_TRADE_DATE = date(2025, 1, 10)


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
        return self.frame.copy()

    def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self.frame.copy()


@dataclass(slots=True)
class CapturingReport:
    seen_frame: pd.DataFrame | None = None

    def generate(self, frame: pd.DataFrame) -> dict[str, Any]:
        self.seen_frame = frame.copy()
        signals = frame[["symbol"]].copy()
        signals["signal"] = "BUY"
        return {"signals": signals}


def _frame(symbol: str = "ALPHA") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": _TRADE_DATE,
                "open": 90,
                "high": 110,
                "low": 80,
                "close": 100,
                "volume": 1000,
                "exchange": "NSE",
            }
        ]
    )


def _canonicalizer() -> CanonicalReplayFrameAdapter:
    identities = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="NEWALPHA",
                exchange="NSE",
                historical_symbols=("ALPHA",),
            ),
        )
    )
    return CanonicalReplayFrameAdapter(identities, CorporateActionTimeline(()))


def test_governed_backtest_consumes_canonical_symbol_and_prices() -> None:
    report = CapturingReport()
    service = GovernedReplayBacktestService(
        canonicalizer=_canonicalizer(),
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(_frame()),
        report=report,
        engine=BacktestEngine(),
    )

    run = service.run(
        strategy="momentum",
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        starting_cash=Decimal("100000"),
    )

    assert report.seen_frame is not None
    assert report.seen_frame.iloc[0]["security_id"] == "SEC-1"
    assert report.seen_frame.iloc[0]["raw_symbol"] == "ALPHA"
    assert report.seen_frame.iloc[0]["symbol"] == "NEWALPHA"
    assert report.seen_frame.iloc[0]["replay_status"] == "READY"
    assert run.summary.positions == {"NEWALPHA": 1}
    assert run.summary.ending_cash == Decimal("99900")


def test_governed_backtest_rejects_unresolved_identity() -> None:
    service = GovernedReplayBacktestService(
        canonicalizer=_canonicalizer(),
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(_frame("UNKNOWN")),
        report=CapturingReport(),
        engine=BacktestEngine(),
    )

    with pytest.raises(ValueError, match="unresolved security identities"):
        service.run(
            strategy="momentum",
            start=_TRADE_DATE,
            end=_TRADE_DATE,
            starting_cash=Decimal("100000"),
        )
