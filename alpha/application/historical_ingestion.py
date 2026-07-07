from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport, DailyReport
from alpha.application.ingestion import IngestionService
from alpha.data.downloader.bhavcopy import BhavcopyDownloader
from alpha.market.resolver import TradingDateResolver


class HistoricalIngestionService:
    """
    Orchestrates historical ingestion and reporting.
    """

    def __init__(
        self,
        resolver: TradingDateResolver | None = None,
        downloader: BhavcopyDownloader | None = None,
        ingestion: IngestionService | None = None,
    ) -> None:
        self.resolver = resolver or TradingDateResolver()
        self.downloader = downloader or BhavcopyDownloader()
        self.ingestion = ingestion or IngestionService()

    def backfill(self, start: date, end: date) -> int:
        processed = 0
        current = start

        while current <= end:
            trading_day = self.resolver.resolve(current)

            archive = self.downloader.download(trading_day)
            self.ingestion.ingest(archive)

            processed += 1
            current += timedelta(days=1)

        return processed

    def download_only(self, date_str: str) -> int:
        target = self._parse(date_str)
        trading_day = self.resolver.resolve(target)
        self.downloader.download(trading_day)
        return 1

    def generate_report(self, date_str: str) -> dict[str, Any]:
        """
        Generate a daily market report.

        If the archive has already been processed, the ingestion pipeline
        returns an empty DataFrame by design. In that idempotent case, reload
        the canonical persisted prices for the trading date before generating
        the report.
        """

        target = self._parse(date_str)
        trading_day = self.resolver.resolve(target)

        archive = self.downloader.download(trading_day)
        df = self.ingestion.ingest(archive)
        df = self._resolve_report_dataframe(df, trading_day)

        report: DailyReport = DailyMarketReport().generate(df)

        return {
            "top_gainers": report["top_gainers"],
            "top_losers": report["top_losers"],
            "regime": report["regime"],
        }

    def _resolve_report_dataframe(
        self,
        ingested: pd.DataFrame,
        trading_day: date,
    ) -> pd.DataFrame:
        if not ingested.empty:
            return ingested

        persisted = self.ingestion.prices.find_by_trade_date(trading_day)
        if not persisted.empty:
            return persisted

        raise ValueError(
            f"No market data available for report date {trading_day.isoformat()}"
        )

    def _parse(self, date_str: str) -> date:
        if date_str == "today":
            return date.today()
        return date.fromisoformat(date_str)
