from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from alpha.application.historical_ingestion import (
    HistoricalBackfillResult,
    HistoricalIngestionService,
)
from alpha.data.downloader.bhavcopy import DownloadedArchive


class FakeResolver:
    def resolve(self, target: date) -> date:
        return target


class FakeDownloader:
    def __init__(self, effective_date: date | None = None) -> None:
        self.downloaded: list[date] = []
        self.effective_date = effective_date

    def download_archive(self, trading_day: date) -> DownloadedArchive:
        self.downloaded.append(trading_day)
        effective_date = self.effective_date or trading_day
        return DownloadedArchive(
            path=Path(f"data/raw/bhavcopy_{effective_date.isoformat()}.zip"),
            requested_date=trading_day,
            trade_date=effective_date,
            cached=False,
        )

    def download(self, trading_day: date) -> Path:
        self.downloaded.append(trading_day)
        effective_date = self.effective_date or trading_day
        return Path(f"data/raw/bhavcopy_{effective_date.isoformat()}.zip")


class FakeLegacyDownloader:
    def __init__(self, effective_date: date) -> None:
        self.downloaded: list[date] = []
        self.effective_date = effective_date

    def download(self, trading_day: date) -> Path:
        self.downloaded.append(trading_day)
        return Path(f"data/raw/bhavcopy_{self.effective_date.isoformat()}.zip")


class FakePricesRepository:
    def __init__(self, persisted: pd.DataFrame) -> None:
        self.persisted = persisted
        self.requested_dates: list[date] = []

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        self.requested_dates.append(trade_date)
        return self.persisted.copy()


class FakeIngestion:
    def __init__(
        self,
        ingested: pd.DataFrame,
        persisted: pd.DataFrame | None = None,
    ) -> None:
        self.ingested = ingested
        self.prices = FakePricesRepository(
            persisted if persisted is not None else pd.DataFrame()
        )
        self.archives: list[Path] = []

    def ingest(self, archive: Path) -> pd.DataFrame:
        self.archives.append(archive)
        return self.ingested.copy()


def _market_frame(trade_date: date = date(2026, 7, 6)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["GAINER", "LOSER", "FLAT"],
            "trade_date": [
                trade_date,
                trade_date,
                trade_date,
            ],
            "open": [100.0, 100.0, 100.0],
            "high": [112.0, 101.0, 100.5],
            "low": [99.0, 89.0, 99.5],
            "close": [110.0, 90.0, 100.0],
            "volume": [1000, 2000, 1500],
            "exchange": ["NSE", "NSE", "NSE"],
        }
    )


def test_backfill_service_can_be_created() -> None:
    service = HistoricalIngestionService()

    assert service is not None
    assert callable(service.backfill)


def test_historical_backfill_result_is_typed() -> None:
    result = HistoricalBackfillResult(
        requested_start=date(2026, 1, 1),
        requested_end=date(2026, 1, 2),
        attempted_days=2,
        processed_archives=1,
        skipped_non_trading_days=0,
        failed_dates=("2026-01-02: missing",),
    )

    assert result.processed_archives == 1
    assert result.failed_dates == ("2026-01-02: missing",)


def test_archive_backfill_skips_weekends_and_ingests_archives(monkeypatch) -> None:
    class FakeArchiveDownloader:
        downloaded: list[date] = []

        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def download_archive(self, trading_day: date) -> DownloadedArchive:
            self.downloaded.append(trading_day)
            return DownloadedArchive(
                path=Path(f"data/raw/bhavcopy_{trading_day.isoformat()}.zip"),
                requested_date=trading_day,
                trade_date=trading_day,
                cached=False,
            )

    monkeypatch.setattr(
        "alpha.application.historical_ingestion.BhavcopyDownloader",
        FakeArchiveDownloader,
    )
    ingestion = FakeIngestion(ingested=_market_frame(date(2026, 1, 2)))
    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    result = service.backfill_legacy_archive(
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
    )

    assert result.attempted_days == 2
    assert result.processed_archives == 2
    assert result.skipped_non_trading_days == 2
    assert FakeArchiveDownloader.downloaded == [
        date(2026, 1, 2),
        date(2026, 1, 5),
    ]
    assert len(ingestion.archives) == 2


def test_generate_report_uses_newly_ingested_prices() -> None:
    downloader = FakeDownloader()
    ingestion = FakeIngestion(ingested=_market_frame())

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    report = service.generate_report("2026-07-06")

    assert downloader.downloaded == [date(2026, 7, 6)]
    assert len(ingestion.archives) == 1
    assert report["observed_on"] == date(2026, 7, 6)
    assert report["top_gainers"].iloc[0]["symbol"] == "GAINER"
    assert ingestion.prices.requested_dates == []


def test_generate_report_reloads_persisted_prices_when_idempotent() -> None:
    downloader = FakeDownloader()
    ingestion = FakeIngestion(
        ingested=pd.DataFrame(),
        persisted=_market_frame(),
    )

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    report = service.generate_report("2026-07-06")

    assert downloader.downloaded == [date(2026, 7, 6)]
    assert len(ingestion.archives) == 1
    assert ingestion.prices.requested_dates == [date(2026, 7, 6)]
    assert report["observed_on"] == date(2026, 7, 6)
    assert report["top_gainers"].iloc[0]["symbol"] == "GAINER"


def test_load_analysis_returns_effective_observed_date_and_analysis_frame() -> None:
    effective_date = date(2026, 7, 7)
    downloader = FakeDownloader(effective_date=effective_date)
    ingestion = FakeIngestion(
        ingested=pd.DataFrame(),
        persisted=_market_frame(effective_date),
    )

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    analysis = service.load_analysis("2026-07-08")

    assert analysis.requested_on == date(2026, 7, 8)
    assert analysis.observed_on == effective_date
    assert "alpha_score" in analysis.analysis.columns
    assert "signal" in analysis.analysis.columns
    assert ingestion.prices.requested_dates == [effective_date]


def test_load_analysis_preserves_persisted_sector_metadata() -> None:
    effective_date = date(2026, 7, 7)
    persisted = _market_frame(effective_date)
    persisted["sector"] = ["BANKS", "IT", "BANKS"]
    downloader = FakeDownloader(effective_date=effective_date)
    ingestion = FakeIngestion(
        ingested=pd.DataFrame(),
        persisted=persisted,
    )

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    analysis = service.load_analysis("2026-07-08")

    assert set(analysis.analysis["sector"]) == {"BANKS", "IT"}


def test_generate_report_reloads_persisted_prices_for_effective_download_date() -> None:
    effective_date = date(2026, 7, 7)
    downloader = FakeDownloader(effective_date=effective_date)
    ingestion = FakeIngestion(
        ingested=pd.DataFrame(),
        persisted=_market_frame(effective_date),
    )

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    report = service.generate_report("2026-07-08")

    assert downloader.downloaded == [date(2026, 7, 8)]
    assert ingestion.prices.requested_dates == [effective_date]
    assert report["observed_on"] == effective_date
    assert report["top_gainers"].iloc[0]["symbol"] == "GAINER"


def test_generate_report_derives_effective_date_from_legacy_archive_path() -> None:
    effective_date = date(2026, 7, 7)
    downloader = FakeLegacyDownloader(effective_date=effective_date)
    ingestion = FakeIngestion(
        ingested=pd.DataFrame(),
        persisted=_market_frame(effective_date),
    )

    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=downloader,  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
    )

    report = service.generate_report("2026-07-08")

    assert downloader.downloaded == [date(2026, 7, 8)]
    assert ingestion.prices.requested_dates == [effective_date]
    assert report["observed_on"] == effective_date


def test_generate_report_raises_when_no_data_exists() -> None:
    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        ingestion=FakeIngestion(ingested=pd.DataFrame()),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="No market data available"):
        service.generate_report("2026-07-06")
