from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from alpha.application.historical_ingestion import HistoricalIngestionService


class FakeResolver:
    def resolve(self, target: date) -> date:
        return target


class FakeDownloader:
    def __init__(self) -> None:
        self.downloaded: list[date] = []

    def download(self, trading_day: date) -> Path:
        self.downloaded.append(trading_day)
        return Path(f"data/raw/bhavcopy_{trading_day.isoformat()}.zip")


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


def _market_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["GAINER", "LOSER", "FLAT"],
            "trade_date": [
                date(2026, 7, 6),
                date(2026, 7, 6),
                date(2026, 7, 6),
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
    assert report["top_gainers"].iloc[0]["symbol"] == "GAINER"


def test_generate_report_raises_when_no_data_exists() -> None:
    service = HistoricalIngestionService(
        resolver=FakeResolver(),  # type: ignore[arg-type]
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        ingestion=FakeIngestion(ingested=pd.DataFrame()),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="No market data available"):
        service.generate_report("2026-07-06")
