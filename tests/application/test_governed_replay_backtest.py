"""Integration tests for the canonical-replay-backed backtest entrypoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from alpha.backtest.engine import BacktestEngine
from alpha.recovery.corporate_actions import CorporateActionTimeline
from alpha.recovery.replay_frame import (
    CanonicalReplayFrameAdapter,
    CanonicalReplayFrameResult,
)
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

from alpha.application.governed_replay_backtest import (
    GovernedReplayBacktestService,
    export_governed_replay_backtest_attestations,
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


class TamperingCanonicalizer(CanonicalReplayFrameAdapter):
    def canonicalize(
        self,
        frame: pd.DataFrame,
        *,
        trade_date: date,
        as_of: date,
    ) -> CanonicalReplayFrameResult:
        result = super().canonicalize(
            frame,
            trade_date=trade_date,
            as_of=as_of,
        )
        result.frame.loc[0, "close"] = 999.0
        return result


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


def _identities() -> SecurityIdentityTimeline:
    return SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="NEWALPHA",
                exchange="NSE",
                historical_symbols=("ALPHA",),
            ),
        )
    )


def _canonicalizer() -> CanonicalReplayFrameAdapter:
    return CanonicalReplayFrameAdapter(_identities(), CorporateActionTimeline(()))


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
    assert report.seen_frame.iloc[0]["canonical_replay_enforced"]
    assert run.summary.positions == {"NEWALPHA": 1}
    assert run.summary.ending_cash == Decimal("99900")
    assert len(run.replay_attestations) == 1
    assert run.replay_attestations[0].trade_date == _TRADE_DATE
    assert len(run.canonical_snapshot_sha256s) == 1
    assert len(run.canonical_frame_sha256s) == 1


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


def test_governed_backtest_revalidates_frame_before_consumption() -> None:
    canonicalizer = TamperingCanonicalizer(
        _identities(),
        CorporateActionTimeline(()),
    )
    service = GovernedReplayBacktestService(
        canonicalizer=canonicalizer,
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(_frame()),
        report=CapturingReport(),
        engine=BacktestEngine(),
    )

    with pytest.raises(ValueError, match="does not match exact adjusted"):
        service.run(
            strategy="momentum",
            start=_TRADE_DATE,
            end=_TRADE_DATE,
            starting_cash=Decimal("100000"),
        )


def test_governed_backtest_exports_consumed_replay_proofs(tmp_path: Path) -> None:
    run = GovernedReplayBacktestService(
        canonicalizer=_canonicalizer(),
        resolver=FakeResolver(),
        downloader=FakeDownloader(),
        ingestion=FakeIngestion(_frame()),
        report=CapturingReport(),
        engine=BacktestEngine(),
    ).run(
        strategy="momentum",
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        starting_cash=Decimal("100000"),
    )

    paths = export_governed_replay_backtest_attestations(run, tmp_path)

    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload[0]["canonical_replay_enforced"] is True
    assert payload[0]["trade_date"] == _TRADE_DATE.isoformat()
