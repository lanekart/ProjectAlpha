from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport, DailyReport
from alpha.application.ingestion import IngestionService
from alpha.data.downloader.bhavcopy import BhavcopyDownloader, DownloadedArchive
from alpha.market.resolver import TradingDateResolver


@dataclass(frozen=True, slots=True)
class MarketAnalysisResult:
    """
    Canonical analyzed market data produced by the ingestion/reporting pipeline.

    Application workflows that need analyzed market state should consume this
    object instead of independently downloading, ingesting, and rebuilding the
    analysis frame.
    """

    observed_on: date
    requested_on: date
    analysis: pd.DataFrame
    report: DailyReport


class HistoricalIngestionService:
    """
    Orchestrates historical ingestion and reporting.
    """

    def __init__(
        self,
        resolver: TradingDateResolver | None = None,
        downloader: BhavcopyDownloader | None = None,
        ingestion: IngestionService | None = None,
        report: DailyMarketReport | None = None,
    ) -> None:
        self.resolver = resolver or TradingDateResolver()
        self.downloader = downloader or BhavcopyDownloader()
        self.ingestion = ingestion or IngestionService()
        self.report = report or DailyMarketReport()

    def backfill(self, start: date, end: date) -> int:
        processed = 0
        current = start

        while current <= end:
            trading_day = self.resolver.resolve(current)

            archive = self._download_archive(trading_day)
            self.ingestion.ingest(archive.path)

            processed += 1
            current += timedelta(days=1)

        return processed

    def download_only(self, date_str: str) -> int:
        target = self._parse(date_str)
        trading_day = self.resolver.resolve(target)
        self._download_archive(trading_day)
        return 1

    def load_analysis(self, date_str: str) -> MarketAnalysisResult:
        """
        Load the canonical analyzed market frame for a requested date.

        The requested date may differ from the effective observed trading date
        when the provider falls back to the latest available NSE archive.
        Downstream consumers must use ``observed_on`` as the canonical market
        date.
        """

        target = self._parse(date_str)
        requested_trading_day = self.resolver.resolve(target)

        archive = self._download_archive(requested_trading_day)
        df = self.ingestion.ingest(archive.path)
        df = self._resolve_report_dataframe(df, archive.trade_date)

        report = self.report.generate(df)

        return MarketAnalysisResult(
            observed_on=archive.trade_date,
            requested_on=archive.requested_date,
            analysis=report["analysis"],
            report=report,
        )

    def generate_report(self, date_str: str) -> dict[str, Any]:
        """
        Generate a daily market report.

        If the archive has already been processed, the ingestion pipeline
        returns an empty DataFrame by design. In that idempotent case, reload
        the canonical persisted prices for the effective downloaded trade date
        before generating the report.
        """

        analysis = self.load_analysis(date_str)
        report = analysis.report

        return {
            "observed_on": analysis.observed_on,
            "requested_on": analysis.requested_on,
            "top_gainers": report["top_gainers"],
            "top_losers": report["top_losers"],
            "regime": report["regime"],
            "signals": report["signals"],
        }

    def _download_archive(self, trading_day: date) -> DownloadedArchive:
        download_archive = getattr(self.downloader, "download_archive", None)
        if callable(download_archive):
            archive = download_archive(trading_day)
            if isinstance(archive, DownloadedArchive):
                return archive

        archive_path = self.downloader.download(trading_day)
        return DownloadedArchive(
            path=archive_path,
            requested_date=trading_day,
            trade_date=self._trade_date_from_archive_path(
                archive_path,
                fallback=trading_day,
            ),
            cached=False,
        )

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

    @staticmethod
    def _trade_date_from_archive_path(path: Path, *, fallback: date) -> date:
        stem = path.stem
        prefix = "bhavcopy_"
        if not stem.startswith(prefix):
            return fallback

        try:
            return date.fromisoformat(stem.removeprefix(prefix))
        except ValueError:
            return fallback


__all__ = ["HistoricalIngestionService", "MarketAnalysisResult"]
