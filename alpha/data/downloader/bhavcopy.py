from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.config import settings
from alpha.data.providers.base import MarketDataProvider
from alpha.data.providers.chain import MarketDataProviderChain
from alpha.data.providers.nse import NSEArchiveBhavcopyProvider
from alpha.data.providers.nse_live import NSEUdiffBhavcopyProvider


@dataclass(frozen=True, slots=True)
class DownloadedArchive:
    """
    Canonical downloaded bhavcopy artifact.

    The requested date and effective trade date can differ when the provider
    falls back to the latest available NSE archive. Application services must
    use trade_date for downstream ingestion, reporting, and analytics.
    """

    path: Path
    requested_date: date
    trade_date: date
    cached: bool


class BhavcopyDownloader:
    """
    Orchestrates bhavcopy download and local storage with caching.

    The default provider is a production provider chain:

    1. NSE UDiFF provider for latest/current bhavcopy files.
    2. NSE historical archive provider for older files and fallback.

    Tests and higher-level services may still inject any MarketDataProvider.
    """

    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.provider = provider or _default_provider_chain()
        self.data_dir = data_dir or settings.raw_data_dir

        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download(self, target_date: date) -> Path:
        """
        Download a bhavcopy and return the local archive path.

        This method is retained for backward compatibility. New application
        workflows should prefer download_archive() so the effective trade date
        is not lost when providers fall back to a nearby available archive.
        """

        return self.download_archive(target_date).path

    def download_archive(self, target_date: date) -> DownloadedArchive:
        """
        Download a bhavcopy and return the canonical archive artifact.

        If the requested file already exists, returns it as a cached artifact
        for the requested/effective date.

        When a provider resolves to a nearby available trading date, the file
        is cached using the actual provider result trade date and that effective
        trade date is preserved in the returned artifact.
        """

        requested_file_path = self._file_path(target_date)
        if requested_file_path.exists():
            return DownloadedArchive(
                path=requested_file_path,
                requested_date=target_date,
                trade_date=target_date,
                cached=True,
            )

        result = self.provider.download_bhavcopy(target_date)
        resolved_file_path = self._file_path(result.trade_date)

        if resolved_file_path.exists():
            return DownloadedArchive(
                path=resolved_file_path,
                requested_date=target_date,
                trade_date=result.trade_date,
                cached=True,
            )

        resolved_file_path.write_bytes(result.content)
        return DownloadedArchive(
            path=resolved_file_path,
            requested_date=target_date,
            trade_date=result.trade_date,
            cached=False,
        )

    def _file_path(self, trade_date: date) -> Path:
        return self.data_dir / f"bhavcopy_{trade_date.isoformat()}.zip"


def _default_provider_chain() -> MarketDataProviderChain:
    return MarketDataProviderChain(
        providers=(
            NSEUdiffBhavcopyProvider(),
            NSEArchiveBhavcopyProvider(),
        )
    )


__all__ = ["BhavcopyDownloader", "DownloadedArchive"]
