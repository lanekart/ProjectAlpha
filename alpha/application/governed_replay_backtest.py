"""Governed backtest entrypoint backed by canonical historical replay truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.backtest import (
    BacktestApplicationService,
    BacktestRun,
    MarketReportGenerator,
)
from alpha.application.ingestion import IngestionService
from alpha.backtest.broker import BrokerSimulator
from alpha.backtest.engine import BacktestEngine
from alpha.backtest.equity_curve import EquityCurveBuilder
from alpha.backtest.ledger import ExecutionLedger
from alpha.market.resolver import TradingDateResolver
from alpha.market_truth.historical_service import (
    MarketTruthArchiveDownloader as BhavcopyDownloader,
)
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter


class CanonicalReplayIngestionService(IngestionService):
    """Decorate ingestion so every non-empty frame is canonicalized first."""

    def __init__(
        self,
        source: IngestionService,
        canonicalizer: CanonicalReplayFrameAdapter,
    ) -> None:
        self._source = source
        self._canonicalizer = canonicalizer

    def ingest(self, zip_path: Path) -> pd.DataFrame:
        frame = self._source.ingest(zip_path)
        if frame.empty:
            return frame.copy()
        trading_day = _single_trade_date(frame)
        return self._canonicalize(frame, trading_day)

    def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
        frame = self._source.load_prices_for_trade_date(trade_date)
        if frame.empty:
            return frame.copy()
        return self._canonicalize(frame, trade_date)

    def _canonicalize(self, frame: pd.DataFrame, trade_date: date) -> pd.DataFrame:
        result = self._canonicalizer.canonicalize(
            frame,
            trade_date=trade_date,
            as_of=trade_date,
        )
        if not result.audit.passed:
            raise ValueError("canonical replay audit did not pass")
        return result.frame


@dataclass(slots=True)
class GovernedReplayBacktestService:
    """Run the existing backtest pipeline with canonical replay enforced."""

    canonicalizer: CanonicalReplayFrameAdapter
    resolver: TradingDateResolver = field(default_factory=TradingDateResolver)
    downloader: BhavcopyDownloader = field(default_factory=BhavcopyDownloader)
    ingestion: IngestionService = field(default_factory=IngestionService)
    report: MarketReportGenerator = field(default_factory=DailyMarketReport)
    engine: BacktestEngine = field(default_factory=BacktestEngine)
    broker: BrokerSimulator = field(default_factory=BrokerSimulator)
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    equity_curve_builder: EquityCurveBuilder = field(default_factory=EquityCurveBuilder)

    def run(
        self,
        *,
        strategy: str,
        start: date,
        end: date,
        starting_cash: Decimal,
    ) -> BacktestRun:
        governed_ingestion = CanonicalReplayIngestionService(
            source=self.ingestion,
            canonicalizer=self.canonicalizer,
        )
        service = BacktestApplicationService(
            resolver=self.resolver,
            downloader=self.downloader,
            ingestion=governed_ingestion,
            report=self.report,
            engine=self.engine,
            broker=self.broker,
            ledger=self.ledger,
            equity_curve_builder=self.equity_curve_builder,
        )
        return service.run(
            strategy=strategy,
            start=start,
            end=end,
            starting_cash=starting_cash,
        )


def _single_trade_date(frame: pd.DataFrame) -> date:
    if "trade_date" not in frame.columns:
        raise ValueError("governed replay frame is missing trade_date")
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce")
    if parsed.isna().any():
        raise ValueError("governed replay frame contains invalid trade_date values")
    dates = {item.date() for item in parsed}
    if len(dates) != 1:
        rendered = ", ".join(sorted(item.isoformat() for item in dates))
        raise ValueError(f"governed replay frame spans multiple dates: {rendered}")
    return next(iter(dates))
