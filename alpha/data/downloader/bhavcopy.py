from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.config import settings
from alpha.data.providers.base import MarketDataProvider
from alpha.data.providers.chain import MarketDataProviderChain
from alpha.data.providers.nse import NSEArchiveBhavcopyProvider
from alpha.data.providers.nse_live import NSEUdiffBhavcopyProvider


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
        Download a bhavcopy and persist it locally.

        If the requested file already exists, returns the cached file without
        calling the provider.

        When a provider resolves to a nearby available trading date, the file
        is cached using the actual provider result trade date.
        """

        requested_file_path = self._file_path(target_date)
        if requested_file_path.exists():
            return requested_file_path

        result = self.provider.download_bhavcopy(target_date)
        resolved_file_path = self._file_path(result.trade_date)

        if resolved_file_path.exists():
            return resolved_file_path

        resolved_file_path.write_bytes(result.content)
        return resolved_file_path

    def _file_path(self, trade_date: date) -> Path:
        return self.data_dir / f"bhavcopy_{trade_date.isoformat()}.zip"


def _default_provider_chain() -> MarketDataProviderChain:
    return MarketDataProviderChain(
        providers=(
            NSEUdiffBhavcopyProvider(),
            NSEArchiveBhavcopyProvider(),
        )
    )
